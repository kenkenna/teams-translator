"""
Teams Meeting Audio Capture
Runs on Windows — captures WASAPI loopback (system audio) and/or microphone,
then streams raw PCM via WebSocket to the WSL2 FastAPI server.

Usage:
  python capture.py --mode realtime
  python capture.py --mode record --meeting-id 1
  python capture.py --server ws://192.168.x.x:8000
"""

import argparse
import queue
import sys
import threading
import time

import numpy as np
import websocket

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_FRAMES = 1600  # 100ms chunks
FORMAT_BYTES = 2     # int16 = 2 bytes


def find_loopback_device(audio):
    """Find WASAPI loopback device (system audio output)."""
    loopback_index = None
    default_output = audio.get_default_output_device_info()
    target_name = default_output["name"]

    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        if (info.get("isLoopbackDevice", False) and
                target_name in info["name"]):
            loopback_index = i
            print(f"  ループバックデバイス発見: [{i}] {info['name']}")
            return loopback_index

    # Fallback: first loopback device
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        if info.get("isLoopbackDevice", False):
            loopback_index = i
            print(f"  ループバックデバイス発見（フォールバック）: [{i}] {info['name']}")
            return loopback_index

    return None


def find_microphone_device(audio):
    """Find default microphone device."""
    try:
        info = audio.get_default_input_device_info()
        print(f"  マイクデバイス: [{info['index']}] {info['name']}")
        return info["index"]
    except Exception:
        # Fallback: first input device
        for i in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0 and not info.get("isLoopbackDevice", False):
                print(f"  マイクデバイス（フォールバック）: [{i}] {info['name']}")
                return i
    return None


def resample_if_needed(audio_data: np.ndarray, src_rate: int, dst_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Simple linear resampling if sample rates differ."""
    if src_rate == dst_rate:
        return audio_data
    ratio = dst_rate / src_rate
    new_length = int(len(audio_data) * ratio)
    return np.interp(
        np.linspace(0, len(audio_data) - 1, new_length),
        np.arange(len(audio_data)),
        audio_data,
    ).astype(np.float32)


def to_mono_float32(pcm_bytes: bytes, channels: int, dtype=np.int16) -> np.ndarray:
    """Convert raw PCM bytes to mono float32."""
    samples = np.frombuffer(pcm_bytes, dtype=dtype).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples / 32768.0


def float32_to_int16_bytes(samples: np.ndarray) -> bytes:
    """Convert float32 numpy array to int16 PCM bytes."""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


class AudioCapture:
    def __init__(self, server_url: str, mode: str, meeting_id: int | None) -> None:
        self.server_url = server_url
        self.mode = mode
        self.meeting_id = meeting_id
        self.audio_queue: queue.Queue[bytes] = queue.Queue()
        self.running = False
        self.ws = None

    def _build_ws_url(self) -> str:
        params = [f"mode={self.mode}"]
        if self.meeting_id is not None:
            params.append(f"meeting_id={self.meeting_id}")
        return f"{self.server_url}/ws/capture?{'&'.join(params)}"

    def _loopback_callback(self, in_data, frame_count, time_info, status):
        self.audio_queue.put(("loopback", in_data))
        return (None, 0)  # pyaudio.paContinue

    def _mic_callback(self, in_data, frame_count, time_info, status):
        self.audio_queue.put(("mic", in_data))
        return (None, 0)

    def run_realtime(self) -> None:
        """Realtime mode: capture loopback only, stream immediately."""
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            print("エラー: pyaudiowpatch がインストールされていません。")
            print("  pip install pyaudiowpatch")
            sys.exit(1)

        pa = pyaudio.PyAudio()
        loopback_idx = find_loopback_device(pa)
        if loopback_idx is None:
            print("エラー: ループバックデバイスが見つかりません。")
            pa.terminate()
            sys.exit(1)

        device_info = pa.get_device_info_by_index(loopback_idx)
        src_rate = int(device_info["defaultSampleRate"])
        src_channels = min(int(device_info["maxInputChannels"]), 2)

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=src_channels,
            rate=src_rate,
            input=True,
            input_device_index=loopback_idx,
            frames_per_buffer=CHUNK_FRAMES,
            stream_callback=self._loopback_callback,
        )
        stream.start_stream()
        print("キャプチャ開始... Ctrl+Cで停止")

        try:
            while self.running and stream.is_active():
                try:
                    _, pcm_bytes = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                samples = to_mono_float32(pcm_bytes, src_channels)
                samples = resample_if_needed(samples, src_rate)
                out_bytes = float32_to_int16_bytes(samples)

                if self.ws and self.ws.sock and self.ws.sock.connected:
                    self.ws.send_binary(out_bytes)
                    print(f"  送信中: {len(out_bytes)}バイト", end="\r")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def run_record(self) -> None:
        """Record mode: capture loopback + mic, mix and stream."""
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            print("エラー: pyaudiowpatch がインストールされていません。")
            print("  pip install pyaudiowpatch")
            sys.exit(1)

        pa = pyaudio.PyAudio()
        loopback_idx = find_loopback_device(pa)
        mic_idx = find_microphone_device(pa)

        if loopback_idx is None:
            print("警告: ループバックデバイスが見つかりません。マイクのみ録音します。")

        lb_info = pa.get_device_info_by_index(loopback_idx) if loopback_idx is not None else None
        mic_info = pa.get_device_info_by_index(mic_idx) if mic_idx is not None else None

        lb_rate = int(lb_info["defaultSampleRate"]) if lb_info else SAMPLE_RATE
        lb_ch   = min(int(lb_info["maxInputChannels"]), 2) if lb_info else 1
        mic_rate = int(mic_info["defaultSampleRate"]) if mic_info else SAMPLE_RATE
        mic_ch   = min(int(mic_info["maxInputChannels"]), 2) if mic_info else 1

        lb_buf:  dict[str, bytes] = {}
        mic_buf: dict[str, bytes] = {}
        mix_queue: queue.Queue[bytes] = queue.Queue()

        def _lb_cb(in_data, frame_count, time_info, status):
            self.audio_queue.put(("loopback", in_data))
            return (None, 0)

        def _mic_cb(in_data, frame_count, time_info, status):
            self.audio_queue.put(("mic", in_data))
            return (None, 0)

        streams = []

        if loopback_idx is not None:
            lb_stream = pa.open(
                format=pyaudio.paInt16,
                channels=lb_ch,
                rate=lb_rate,
                input=True,
                input_device_index=loopback_idx,
                frames_per_buffer=CHUNK_FRAMES,
                stream_callback=_lb_cb,
            )
            lb_stream.start_stream()
            streams.append(lb_stream)

        if mic_idx is not None:
            mic_stream = pa.open(
                format=pyaudio.paInt16,
                channels=mic_ch,
                rate=mic_rate,
                input=True,
                input_device_index=mic_idx,
                frames_per_buffer=CHUNK_FRAMES,
                stream_callback=_mic_cb,
            )
            mic_stream.start_stream()
            streams.append(mic_stream)

        print("キャプチャ開始（録音モード）... Ctrl+Cで停止")

        lb_pending = np.array([], dtype=np.float32)
        mic_pending = np.array([], dtype=np.float32)

        try:
            while self.running:
                try:
                    source, pcm_bytes = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                samples = to_mono_float32(pcm_bytes, lb_ch if source == "loopback" else mic_ch)

                if source == "loopback":
                    samples = resample_if_needed(samples, lb_rate)
                    lb_pending = np.concatenate([lb_pending, samples])
                else:
                    samples = resample_if_needed(samples, mic_rate)
                    mic_pending = np.concatenate([mic_pending, samples])

                # Mix when both have enough data
                min_len = min(len(lb_pending), len(mic_pending))
                if min_len >= CHUNK_FRAMES:
                    lb_chunk  = lb_pending[:min_len]
                    mic_chunk = mic_pending[:min_len]
                    lb_pending  = lb_pending[min_len:]
                    mic_pending = mic_pending[min_len:]

                    # Average mix
                    mixed = (lb_chunk + mic_chunk) / 2.0
                    out_bytes = float32_to_int16_bytes(mixed)

                    if self.ws and self.ws.sock and self.ws.sock.connected:
                        self.ws.send_binary(out_bytes)
                        print(f"  送信中: {len(out_bytes)}バイト", end="\r")
        finally:
            for s in streams:
                s.stop_stream()
                s.close()
            pa.terminate()

    def start(self) -> None:
        ws_url = self._build_ws_url()
        print(f"接続中: {ws_url}")

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_ws_open,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )

        ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        ws_thread.start()

        # Wait for connection
        for _ in range(30):
            if self.ws.sock and self.ws.sock.connected:
                break
            time.sleep(0.1)
        else:
            print("エラー: サーバーへの接続がタイムアウトしました。")
            sys.exit(1)

        self.running = True
        try:
            if self.mode == "realtime":
                self.run_realtime()
            else:
                self.run_record()
        except KeyboardInterrupt:
            print("\n\n停止中...")
        finally:
            self.running = False
            if self.ws:
                self.ws.close()
            print("キャプチャを終了しました。")

    def _on_ws_open(self, ws) -> None:
        print("WebSocket 接続完了")

    def _on_ws_error(self, ws, error) -> None:
        print(f"WebSocket エラー: {error}")

    def _on_ws_close(self, ws, close_status_code, close_msg) -> None:
        print(f"WebSocket 切断 (code={close_status_code})")
        self.running = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teams会議音声キャプチャ & WebSocketストリーマー",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # リアルタイム翻訳モード（リモート参加者の音声のみ）
  python capture.py --mode realtime

  # 録音モード（マイク + システム音声）
  python capture.py --mode record --meeting-id 1

  # WSL2のIPアドレスを指定
  python capture.py --mode realtime --server ws://172.28.0.1:8000
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["realtime", "record"],
        default="realtime",
        help="キャプチャモード (default: realtime)",
    )
    parser.add_argument(
        "--meeting-id",
        type=int,
        default=None,
        help="録音モード時の会議ID",
    )
    parser.add_argument(
        "--server",
        default="ws://localhost:8000",
        help="FastAPIサーバーのWebSocket URL (default: ws://localhost:8000)",
    )

    args = parser.parse_args()

    if args.mode == "record" and args.meeting_id is None:
        print("エラー: 録音モードでは --meeting-id が必要です。")
        print("  先にブラウザで会議を作成するか、以下のコマンドで作成してください:")
        print('  curl -X POST http://localhost:8000/api/meetings -H "Content-Type: application/json" -d "{\\"name\\": \\"会議名\\"}"')
        sys.exit(1)

    print("=" * 50)
    print("Teams 会議音声キャプチャ")
    print(f"  モード     : {args.mode}")
    print(f"  サーバー   : {args.server}")
    if args.meeting_id:
        print(f"  会議ID     : {args.meeting_id}")
    print("=" * 50)

    capture = AudioCapture(
        server_url=args.server,
        mode=args.mode,
        meeting_id=args.meeting_id,
    )
    capture.start()


if __name__ == "__main__":
    main()
