import { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import RecordRTC from 'recordrtc';

export default function Register({ onComplete }) {
  const [fullName, setFullName] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [mpin, setMpin] = useState('');
  const [status, setStatus] = useState({ text: '', type: '' });
  const [loading, setLoading] = useState(false);

  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);

  useEffect(() => {
    const currentVideo = videoRef.current;

    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then((stream) => {
        if (currentVideo) currentVideo.srcObject = stream;
        
        const recorder = new RecordRTC(stream, {
          type: 'audio',
          mimeType: 'audio/wav',
          recorderType: RecordRTC.StereoAudioRecorder,
          desiredSampRate: 16000,
          numberOfAudioChannels: 1
        });
        
        recorder.startRecording();
        mediaRecorderRef.current = recorder;
      })
      .catch((err) => {
        // ESLINT FIX: Actively using the 'err' variable
        console.error("Camera/Mic access error:", err);
        setStatus({ text: "Camera & Microphone access is strictly required.", type: 'error' });
      });

    return () => {
      if (currentVideo && currentVideo.srcObject) {
        currentVideo.srcObject.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    setLoading(true);
    setStatus({ text: 'Extracting Face & Voice Signatures...', type: 'loading' });

    const captureAndSend = async (audioBlob) => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = videoRef.current.videoWidth || 640;
        canvas.height = videoRef.current.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(videoRef.current, 0, 0);

        const frameBlob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.9));

        const formData = new FormData();
        formData.append('full_name', fullName);
        formData.append('customer_id', customerId);
        formData.append('mpin', mpin);
        formData.append('frame', frameBlob, 'frame.jpg');
        formData.append('audio', audioBlob, 'voice.wav');

        await axios.post('http://127.0.0.1:8000/register', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        setStatus({ text: 'Biometrics Linked & Account Created! Redirecting...', type: 'success' });
        setTimeout(() => onComplete(), 1500);
      } catch (err) {
        setStatus({ text: 'Registration Failed: ' + (err.response?.data?.detail || err.message), type: 'error' });
        
        if (mediaRecorderRef.current) {
          mediaRecorderRef.current.reset();
          mediaRecorderRef.current.startRecording();
        }
        setLoading(false);
      }
    };

    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stopRecording(() => {
        const audioBlob = mediaRecorderRef.current.getBlob();
        captureAndSend(audioBlob);
      });
    }
  };

  return (
    <div className="bg-white p-8 rounded-2xl shadow-xl border border-slate-100">
      <h2 className="text-2xl font-bold mb-2 text-slate-800">Enroll Biometrics</h2>
      
      <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-xl">
        <p className="text-xs font-bold text-blue-800 uppercase tracking-wider mb-1">Required Actions:</p>
        <p className="text-sm font-medium text-blue-900">
          Look directly into the camera and read the following passphrase aloud while registering:
          <br/><span className="text-base font-black italic mt-2 block">"My voice is my password and my identity is secure."</span>
        </p>
      </div>
      
      <div className="mb-6 overflow-hidden rounded-xl bg-slate-900 border-2 border-slate-100 shadow-inner relative">
        <video ref={videoRef} autoPlay playsInline muted className="w-full h-48 object-cover transform scale-x-[-1]" />
        <div className="absolute top-3 right-3 flex items-center bg-black/50 px-2 py-1 rounded-full backdrop-blur-sm">
          <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse mr-2"></div>
          <span className="text-[10px] font-bold text-white uppercase tracking-wider">Recording Signature</span>
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
        <button type="submit" disabled={loading} className="w-full py-3.5 mt-2 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-70 flex justify-center items-center">
          {loading ? 'Processing Identity...' : 'Link Biometrics & Register'}
        </button>
      </form>
      {status.text && (
        <p className={`mt-5 text-sm text-center font-medium ${status.type === 'error' ? 'text-red-500 bg-red-50 p-2 rounded-lg' : 'text-emerald-600'}`}>{status.text}</p>
      )}
    </div>
  );
}