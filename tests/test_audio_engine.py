import pytest
import numpy as np
import sys
from unittest.mock import MagicMock, patch
from app.audio_engine import AudioEngine

@pytest.fixture
def mock_sd():
    with patch("app.audio_engine.sd") as mock:
        # Default mock behavior
        mock_device = {"name": "Mock Input", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 44100}
        
        def query_devices_mock(index=None, kind=None):
            if index is None and kind is None:
                return [mock_device]
            return mock_device
            
        mock.query_devices.side_effect = query_devices_mock
        mock.query_hostapis.return_value = {"name": "MME"}
        mock.default.device = [0, 0]
        
        # Mock InputStream to return a mock stream
        mock_stream = MagicMock()
        mock.InputStream.return_value = mock_stream
        
        yield mock

def test_list_devices(mock_sd):
    devices = AudioEngine.list_devices()
    assert len(devices) == 1
    assert devices[0]["name"] == "Mock Input"
    assert devices[0]["hostapi"] == "MME"

def test_engine_init():
    engine = AudioEngine(sample_rate=48000, block_size=512)
    assert engine.sample_rate == 48000
    assert engine.block_size == 512
    assert engine.channels == 2
    assert engine._is_py314 == (sys.version_info.major == 3 and sys.version_info.minor == 14)

def test_start_stop_stream(mock_sd):
    engine = AudioEngine()
    engine.start(device_index=0)
    
    assert mock_sd.InputStream.called
    assert engine.is_running
    
    engine.stop()
    assert engine._stream is None
    assert not engine.is_running
    assert mock_sd.InputStream.return_value.abort.called
    assert mock_sd.InputStream.return_value.close.called

def test_cleanup_stream_safe():
    AudioEngine._cleanup_stream(None)

    mock_stream = MagicMock()
    mock_stream.abort.side_effect = RuntimeError("Abort error")
    mock_stream.close.side_effect = RuntimeError("Close error")
    # Should not raise
    AudioEngine._cleanup_stream(mock_stream)
    assert mock_stream.abort.called
    assert mock_stream.close.called

def test_audio_callback_guards():
    engine = AudioEngine()
    engine._audio_callback(None, 0, None, 0)
    engine._audio_callback(np.zeros(0, dtype=np.float32), 0, None, 0)
    engine._audio_callback_mono(None, 0, None, 0)
    engine._audio_callback_mono(np.zeros(0, dtype=np.float32), 0, None, 0)
    assert engine._queue.empty()

def test_drain_queue_emits_data():
    # This requires qtbot from pytest-qt if we want to check signals
    # But we can also check internal state
    engine = AudioEngine()
    test_data = np.random.randn(1024, 2).astype(np.float32)
    engine._queue.put(test_data)
    
    # Mock the data_ready signal
    engine.data_ready = MagicMock()
    
    engine._drain_queue()
    
    assert engine.data_ready.emit.called
    # Check if buffer was updated
    assert engine._total_written == 1024
    np.testing.assert_allclose(engine.buffer[:1024], test_data)

def test_py314_workaround_logic(mock_sd, monkeypatch):
    # Force _is_py314 to True for this test
    engine = AudioEngine()
    monkeypatch.setattr(engine, "_is_py314", True)
    engine.sample_rate = 44100
    engine.block_size = 1024
    
    # Test silence detection
    # We need to simulate many calls to _handle_silence_fallback to trigger the 1.5s threshold
    # 44100 * 1.5 = 66150 frames.
    # With 1024 frames per call, we need ~65 calls.
    
    for _ in range(60):
        engine._handle_silence_fallback(is_silent=True, frames=1024)
        assert engine._fallback_stream is None # Not yet triggered
        
    # Trigger it
    engine._handle_silence_fallback(is_silent=True, frames=10000)
    assert mock_sd.OutputStream.called
    assert engine._fallback_stream is not None
    
    # Test recovery from silence
    engine._handle_silence_fallback(is_silent=False, frames=1024)
    assert engine._silence_counter == 0
    assert engine._fallback_stream is None

def test_get_history():
    engine = AudioEngine(sample_rate=100, buffer_seconds=1.0) # Small buffer for testing
    data = np.ones((50, 2), dtype=np.float32)
    engine._queue.put(data)
    engine._drain_queue()
    
    history = engine.get_history(0.2) # 20 samples
    assert history.shape == (20, 2)
    assert np.all(history == 1.0)
    
    # Test wrap around
    data2 = np.zeros((70, 2), dtype=np.float32) # Total 120, buffer is 100
    engine._queue.put(data2)
    engine._drain_queue()
    
    history = engine.get_history(0.5) # 50 samples
    assert history.shape == (50, 2)
    assert np.all(history == 0.0) # Should all be from data2

def test_drain_queue_preserves_contiguous_samples_on_backlog():
    engine = AudioEngine(block_size=512)
    engine.data_ready = MagicMock()
    # Queue up 6 blocks (3072 samples)
    for _ in range(6):
        engine._queue.put(np.ones((512, 2), dtype=np.float32))

    engine._drain_queue()

    # Full 3072 samples must be written to circular buffer and emitted in full
    # to preserve phase continuity for high sample modules (32k FFT, 8.1k oscilloscope)
    assert engine._total_written == 3072
    emitted = engine.data_ready.emit.call_args[0][0]
    assert len(emitted) == 3072

