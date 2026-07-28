import { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import RecordRTC from 'recordrtc';

export default function Register({ onComplete }) {
  const [fullName, setFullName] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [mpin, setMpin] = useState('');
  const [status, setStatus] = useState({ text: '', type: '' });
  const [loading, setLoading] = useState(false);

  // Recording control states - mirrors Login.jsx's explicit start/countdown flow
  const [recordingState, setRecordingState] = useState('idle'); // 'idle' | 'recording' | 'done'
  const [recordingSeconds, setRecordingSeconds] = useState(4);
  const RECORD_SECONDS = 4;

  const videoRef = useRef(null);
  const mediaStreamRef = useRef(null); // full A/V stream, used for video preview + frame capture
  const audioStreamRef = useRef(null); // audio-only sub-stream, used for the voice recorder
  const recorderRef = useRef(null);
  const audioBlobRef = useRef(null);
  const countdownIntervalRef = useRef(null);

  useEffect(() => {
    const currentVideo = videoRef.current;
    let currentStream = null;

    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then((stream) => {
        currentStream = stream;
        mediaStreamRef.current = stream;
        if (currentVideo) currentVideo.srcObject = stream;

        // IMPORTANT: only hand the audio track(s) to the recorder. Handing
        // RecordRTC the full audio+video stream is what was silently
        // producing empty/unreliable voice captures - pulling just the
        // audio tracks into their own MediaStream makes recording reliable.
        const audioOnlyStream = new MediaStream(stream.getAudioTracks());
        audioStreamRef.current = audioOnlyStream;
      })
      .catch((err) => {
        console.error("Camera/Mic access error:", err);
        setStatus({ text: "Camera & Microphone access is strictly required.", type: 'error' });
      });

    return () => {
      if (countdownIntervalRef.current) clearInterval(countdownIntervalRef.current);
      if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const startVoiceRecording = () => {
    if (!audioStreamRef.current || audioStreamRef.current.getAudioTracks().length === 0) {
      alert("Microphone stream not ready yet. Please wait a moment and try again.");
      return;
    }

    audioBlobRef.current = null;

    const recorder = new RecordRTC(audioStreamRef.current, {
      type: 'audio',
      mimeType: 'audio/wav',
      recorderType: RecordRTC.StereoAudioRecorder,
      desiredSampRate: 16000,
      numberOfAudioChannels: 1
    });

    recorder.startRecording();
    recorderRef.current = recorder;
    setRecordingState('recording');
    setRecordingSeconds(RECORD_SECONDS);

    let timeLeft = RECORD_SECONDS;
    countdownIntervalRef.current = setInterval(() => {
      timeLeft -= 1;
      if (timeLeft > 0) {
        setRecordingSeconds(timeLeft);
      } else {
        clearInterval(countdownIntervalRef.current);
        setRecordingSeconds(0);
        recorder.stopRecording(() => {
          audioBlobRef.current = recorder.getBlob();
          setRecordingState('done');
        });
      }
    }, 1000);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (recordingState !== 'done' || !audioBlobRef.current) {
      alert("Please record your voice sample first (read the passphrase aloud).");
      return;
    }

    setLoading(true);
    setStatus({ text: 'Extracting Face & Voice Signatures...', type: 'loading' });

    try {
      const canvas = document.createElement('canvas');
      canvas.width = videoRef.current?.videoWidth || 640;
      canvas.height = videoRef.current?.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      if (videoRef.current) {
        ctx.drawImage(videoRef.current, 0, 0);
      }

      const frameBlob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.9));

      const formData = new FormData();
      formData.append('full_name', fullName);
      formData.append('customer_id', customerId);
      formData.append('mpin', mpin);
      formData.append('frame', frameBlob, 'frame.jpg');
      formData.append('audio', audioBlobRef.current, 'voice.wav');

      await axios.post('http://127.0.0.1:8000/register', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      setStatus({ text: 'Biometrics Linked & Account Created! Redirecting...', type: 'success' });
      setTimeout(() => onComplete(), 1500);
    } catch (err) {
      setStatus({ text: 'Registration Failed: ' + (err.response?.data?.detail || err.message), type: 'error' });
      setLoading(false);
    }
  };

  const resetVoiceRecording = () => {
    audioBlobRef.current = null;
    setRecordingState('idle');
    setRecordingSeconds(RECORD_SECONDS);
  };

  return (
    <div className="bg-white p-8 rounded-2xl shadow-xl border border-slate-100">
      <h2 className="text-2xl font-bold mb-2 text-slate-800">Enroll Biometrics</h2>

      <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-xl">
        <p className="text-xs font-bold text-blue-800 uppercase tracking-wider mb-1">Required Actions:</p>
        <p className="text-sm font-medium text-blue-900">
          Look directly into the camera, then click "Start Recording" and read the following passphrase aloud:
          <br/><span className="text-base font-black italic mt-2 block">"My voice is my password and my identity is secure."</span>
        </p>
      </div>

      <div className="mb-6 overflow-hidden rounded-xl bg-slate-900 border-2 border-slate-100 shadow-inner relative">
        <video ref={videoRef} autoPlay playsInline muted className="w-full h-48 object-cover transform scale-x-[-1]" />
        {recordingState === 'recording' && (
          <div className="absolute top-3 right-3 flex items-center bg-black/50 px-2 py-1 rounded-full backdrop-blur-sm">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse mr-2"></div>
            <span className="text-[10px] font-bold text-white uppercase tracking-wider">Recording ({recordingSeconds}s)</span>
          </div>
        )}
      </div>

      {/* Voice Recording Control Box - mirrors the login screen's flow */}
      <div className="mb-6 p-4 rounded-xl border border-slate-200 bg-slate-50">
        <div className="flex justify-between items-center">
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
          {recordingState === 'done' && (
            <button
              type="button"
              onClick={resetVoiceRecording}
              className="px-3 py-1 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-bold shadow transition-colors cursor-pointer"
            >
              Re-record
            </button>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Full Name</label>
          <input type="text" required value={fullName} onChange={(e) => setFullName(e.target.value)} className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all" />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Customer ID / Mobile</label>
          <input type="text" required value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all" />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">4-Digit MPIN</label>
          <input type="password" maxLength={4} required value={mpin} onChange={(e) => setMpin(e.target.value)} className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all tracking-widest text-lg" />
        </div>
        <button
          type="submit"
          disabled={loading || recordingState !== 'done'}
          className="w-full py-3.5 mt-2 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center"
        >
          {loading ? 'Processing Identity...' : recordingState !== 'done' ? 'Please record your voice sample first' : 'Link Biometrics & Register'}
        </button>
      </form>
      {status.text && (
        <p className={`mt-5 text-sm text-center font-medium ${status.type === 'error' ? 'text-red-500 bg-red-50 p-2 rounded-lg' : 'text-emerald-600'}`}>{status.text}</p>
      )}
    </div>
  );
}