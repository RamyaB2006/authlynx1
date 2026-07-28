import { useEffect, useState, useRef, useCallback } from 'react';
import axios from 'axios';

export default function Login({ onLoginSuccess }) {
  const [customerId, setCustomerId] = useState('');
  const [mpin, setMpin] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Recording control states
  const [recordingState, setRecordingState] = useState('idle'); // 'idle' | 'recording' | 'done'
  const [recordingSeconds, setRecordingSeconds] = useState(4);
  const RECORD_SECONDS = 4; // matches Register.jsx so both voiceprints come from comparable-length speech

  const videoRef = useRef(null);
  const mediaStreamRef = useRef(null);   // full A/V stream - used for the video preview + frame capture
  const audioStreamRef = useRef(null);   // audio-only sub-stream - used for the voice recorder
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const canvasRef = useRef(null);
  const animationFrameRef = useRef(null);

  const drawVisualizer = useCallback(() => {
    if (!canvasRef.current || !analyserRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const analyser = analyserRef.current;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const render = () => {
      animationFrameRef.current = requestAnimationFrame(render);
      analyser.getByteFrequencyData(dataArray);

      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const barWidth = (canvas.width / bufferLength) * 2.5;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        const barHeight = (dataArray[i] / 255) * canvas.height;
        ctx.fillStyle = '#10b981';
        ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
        x += barWidth + 1;
      }
    };
    render();
  }, []);

  // Initialize camera preview on mount, but keep microphone recording stopped until requested
  useEffect(() => {
    let currentStream = null;

    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then((stream) => {
        currentStream = stream;
        mediaStreamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }

        // Only the audio track(s) go to the recorder/analyser. Recording from
        // the combined video+audio stream was producing a muxed video/webm
        // container labelled as "audio", which some browsers/codecs decode
        // unreliably on the backend - splitting it out fixes both the
        // "recording doesn't seem to capture anything" issue and downstream
        // voice-match failures caused by corrupted/garbled audio extraction.
        const audioOnlyStream = new MediaStream(stream.getAudioTracks());
        audioStreamRef.current = audioOnlyStream;

        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        audioContextRef.current = audioCtx;
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 64;
        analyserRef.current = analyser;

        const source = audioCtx.createMediaStreamSource(audioOnlyStream);
        source.connect(analyser);
      })
      .catch((err) => {
        console.warn("Media warning:", err);
        setError("Camera and microphone access are required for secure login.");
      });

    return () => {
      if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
      }
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  // Function triggered when user clicks "Start Voice Recording"
  const startVoiceRecording = () => {
    if (!audioStreamRef.current || audioStreamRef.current.getAudioTracks().length === 0) {
      alert("Microphone stream not ready.");
      return;
    }

    audioChunksRef.current = [];
    const mediaRecorder = new MediaRecorder(audioStreamRef.current);

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        audioChunksRef.current.push(event.data);
      }
    };

    mediaRecorder.start();
    mediaRecorderRef.current = mediaRecorder;
    setRecordingState('recording');
    setRecordingSeconds(RECORD_SECONDS);

    drawVisualizer();

    // Countdown Timer
    let timeLeft = RECORD_SECONDS;
    const timerInterval = setInterval(() => {
      timeLeft -= 1;
      if (timeLeft > 0) {
        setRecordingSeconds(timeLeft);
      } else {
        clearInterval(timerInterval);
        setRecordingSeconds(0);
        setRecordingState('done');
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
          mediaRecorderRef.current.stop();
        }
      }
    }, 1000);
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    if (recordingState !== 'done') {
      alert("Please record your voice sample first.");
      return;
    }

    setLoading(true);
    setError('');

    try {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
        mediaRecorderRef.current.stop();
      }

      await new Promise(resolve => setTimeout(resolve, 300));

      const actualMimeType = mediaRecorderRef.current?.mimeType || 'audio/webm';
      const audioBlob = new Blob(audioChunksRef.current, { type: actualMimeType });

      const canvas = document.createElement('canvas');
      canvas.width = videoRef.current?.videoWidth || 640;
      canvas.height = videoRef.current?.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      if (videoRef.current) {
        ctx.drawImage(videoRef.current, 0, 0);
      }

      const frameBlob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.9));

      const formData = new FormData();
      formData.append('customer_id', customerId.trim());
      formData.append('mpin', mpin.trim());
      formData.append('role', 'Account Holder');
      formData.append('frame', frameBlob, 'frame.jpg');
      formData.append('audio', audioBlob, 'voice.webm');

      const res = await axios.post('http://127.0.0.1:8000/login', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      onLoginSuccess(res.data);
    } catch (err) {
      if (err.response && err.response.data && err.response.data.detail) {
        setError(typeof err.response.data.detail === 'string' ? err.response.data.detail : JSON.stringify(err.response.data.detail));
      } else {
        setError(err.message || "An unexpected error occurred.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto mt-12 bg-white p-8 rounded-2xl border border-slate-200 shadow-sm">
      <div className="text-center mb-6">
        <h2 className="text-2xl font-black text-slate-900 tracking-tight">Zero-Trust Secure Sign-In</h2>
        <p className="text-sm text-slate-500 font-medium mt-1">Biometric verification required</p>
      </div>

      {/* Video Feed Preview */}
      <div className="mb-6 relative w-full h-44 bg-slate-900 rounded-xl overflow-hidden border border-slate-200 shadow-inner flex items-center justify-center">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-full object-cover transform scale-x-[-1]"
        />
        <div className="absolute top-2 right-2 px-2.5 py-1 bg-black/60 backdrop-blur-md rounded-full text-[10px] font-bold text-white flex items-center space-x-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span>LIVE FACE AI</span>
        </div>
      </div>

      {/* Voice Recording Control Box */}
      <div className="mb-6 p-4 rounded-xl border border-slate-200 bg-slate-50">
        <div className="flex justify-between items-center mb-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
            {recordingState === 'idle' && '🎙️ Voice Sample Required'}
            {recordingState === 'recording' && `🔴 Recording (${recordingSeconds}s remaining)...`}
            {recordingState === 'done' && '✅ Voice Sample Captured'}
          </span>
          {recordingState === 'idle' && (
            <button
              type="button"
              onClick={startVoiceRecording}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow transition-colors cursor-pointer"
            >
              Start Recording
            </button>
          )}
        </div>
        <canvas ref={canvasRef} width="350" height="40" className="w-full rounded bg-white border border-slate-200" />
      </div>

      <form onSubmit={handleLogin} className="space-y-4">
        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Customer ID / Mobile</label>
          <input
            type="text"
            required
            value={customerId}
            onChange={e => setCustomerId(e.target.value)}
            placeholder="Enter Customer ID"
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">4-Digit MPIN</label>
          <input
            type="password"
            maxLength="4"
            required
            value={mpin}
            onChange={e => setMpin(e.target.value)}
            placeholder="••••"
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-medium tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          type="submit"
          disabled={loading || recordingState !== 'done'}
          className="w-full py-4 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer mt-2"
        >
          {loading ? 'Authenticating Biometrics...' : recordingState !== 'done' ? 'Please record your voice sample first' : 'Authenticate Identity'}
        </button>

        {error && (
          <div className="mt-4 p-3.5 rounded-xl text-sm font-bold bg-red-50 text-red-700 border border-red-200 text-center">
            {error}
          </div>
        )}
      </form>
    </div>
  );
}