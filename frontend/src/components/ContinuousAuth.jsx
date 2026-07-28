import { useEffect, useRef, useState, useCallback } from 'react';
import axios from 'axios';

const QUICK_CHECK_INTERVAL_SECONDS = 4; // how often to check for face violations during recording

export default function ContinuousAuth({ token, userId, onSessionExpired }) {
  const [scores, setScores] = useState({
    trust: 92.5,
    faceVerification: 95.0,
    deepfakeDetection: 96.0,
    voiceSpoof: 94.2,
    behavioral: 88.0,
  });
  const [riskLevel, setRiskLevel] = useState('Low (Secure)');
  const [hardwareState, setHardwareState] = useState('Starting Guard...'); // 'Recording' | 'Sleeping'
  const [timer, setTimer] = useState(20);
  const [cameraError, setCameraError] = useState(null);

  const videoRef = useRef(null);

  const getMetrics = () => ({
    typingSpeed: 60 + Math.random() * 15,
    holdTime: 80 + Math.random() * 10,
    latency: 30 + Math.random() * 20,
    rhythm: 0.9 + Math.random() * 0.1,
    errorRate: Math.random() * 1.5,
  });

  const stopRecorderAndFlush = (mediaRecorder) => {
    return new Promise((resolve) => {
      if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        resolve();
        return;
      }
      mediaRecorder.addEventListener('stop', () => resolve(), { once: true });
      mediaRecorder.stop();
    });
  };

  // Grabs a small downscaled JPEG snapshot from the live video element for
  // the fast mid-window face-count check. Kept deliberately low quality/size
  // since this only needs to answer "how many faces?", not a full biometric
  // comparison - keeps the request tiny and fast.
  const captureQuickFrame = useCallback(() => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) return null;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 320 / video.videoWidth);
    canvas.width = video.videoWidth * scale;
    canvas.height = video.videoHeight * scale;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.6));
  }, []);

  const quickFaceCheck = useCallback(async () => {
    const blob = await captureQuickFrame();
    if (!blob) return { violation: false };
    const formData = new FormData();
    formData.append('token', token);
    formData.append('user_id', userId);
    formData.append('frame', blob, 'quick.jpg');
    const res = await axios.post('http://127.0.0.1:8000/quick-face-check', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return res.data;
  }, [token, userId, captureQuickFrame]);


  useEffect(() => {
    if (!token || !userId) return;

    let isMounted = true;
    const videoNode = videoRef.current;
    let activeStream = null;

    const cycleHardware = async () => {
      while (isMounted) {
        let stream = null;
        try {
          // --- PHASE 1: RECORDING (20 seconds) ---
          setHardwareState('Recording');
          setTimer(20);
          setCameraError(null);

          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
          activeStream = stream;
          if (!isMounted) {
            stream.getTracks().forEach(t => t.stop());
            activeStream = null;
            break;
          }

          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            try {
              await videoRef.current.play();
            } catch (playErr) {
              console.warn('video.play() was blocked or failed:', playErr);
            }
          }

          const audioOnlyStream = new MediaStream(stream.getAudioTracks());
          const mediaRecorder = new MediaRecorder(audioOnlyStream);
          const audioChunks = [];
          mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
          };
          mediaRecorder.start();

          let terminatedMidWindow = false;

          for (let i = 20; i > 0; i--) {
            if (!isMounted) break;
            setTimer(i);

            // Mid-window face check: fires every QUICK_CHECK_INTERVAL_SECONDS
            // while still recording, so a no-face/multi-face condition is
            // caught within seconds instead of waiting for the full 20s
            // cycle to complete.
            if (i % QUICK_CHECK_INTERVAL_SECONDS === 0 && i !== 20) {
              try {
                const check = await quickFaceCheck();
                if (!isMounted) break;
                if (check.violation) {
                  isMounted = false;
                  terminatedMidWindow = true;
                  await stopRecorderAndFlush(mediaRecorder);
                  stream.getTracks().forEach(t => t.stop());
                  activeStream = null;
                  if (videoRef.current) videoRef.current.srcObject = null;
                  alert(`🚨 [SECURITY LOCKOUT] ${check.reason || 'Face verification violation'}.\nTerminating session.`);
                  onSessionExpired();
                  break;
                }
              } catch (checkErr) {
                console.warn('Quick face check failed (non-fatal):', checkErr);
              }
            }

            await new Promise((r) => setTimeout(r, 1000));
          }

          if (terminatedMidWindow) break;

          if (!isMounted) {
            await stopRecorderAndFlush(mediaRecorder);
            stream.getTracks().forEach(t => t.stop());
            activeStream = null;
            break;
          }

          const canvas = document.createElement('canvas');
          let frameBlob = null;
          if (videoRef.current && videoRef.current.videoWidth > 0) {
            canvas.width = videoRef.current.videoWidth;
            canvas.height = videoRef.current.videoHeight;
            canvas.getContext('2d').drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
            frameBlob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.8));
          }

          await stopRecorderAndFlush(mediaRecorder);

          stream.getTracks().forEach(track => track.stop());
          activeStream = null;
          if (videoRef.current) videoRef.current.srcObject = null;

          const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

          if (frameBlob && audioBlob.size > 0) {
            const m = getMetrics();
            const formData = new FormData();
            formData.append('token', token);
            formData.append('user_id', userId);
            formData.append('frame', frameBlob, 'frame.jpg');
            formData.append('audio', audioBlob, 'voice.webm');
            formData.append('typing_speed', m.typingSpeed);
            formData.append('hold_time', m.holdTime);
            formData.append('latency', m.latency);
            formData.append('rhythm', m.rhythm);
            formData.append('error_rate', m.errorRate);

            try {
              const res = await axios.post('http://127.0.0.1:8000/verify-session', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
              });
              if (!isMounted) break;

              setScores({
                trust: res.data.trust_score,
                faceVerification: res.data.face_match,
                deepfakeDetection: res.data.deepfake_score,
                voiceSpoof: res.data.voice_match,
                behavioral: res.data.behavioral_score,
              });
              setRiskLevel(res.data.risk_level);

              if (!res.data.is_active || res.data.trust_score <= 30) {
                isMounted = false;
                const reason = res.data.violation_reason ? `\nReason: ${res.data.violation_reason}` : '';
                alert(`🚨 [SECURITY LOCKOUT] Trust score dropped to ${res.data.trust_score} (${res.data.risk_level}).${reason}\nTerminating session.`);
                onSessionExpired();
                break;
              }
            } catch (err) {
              console.error("Auth verify error:", err);
            }
          }

          // --- PHASE 2: SLEEPING (10 seconds) - camera/mic already fully off ---
          if (!isMounted) break;
          setHardwareState('Sleeping');
          setTimer(10);

          for (let i = 10; i > 0; i--) {
            if (!isMounted) break;
            setTimer(i);
            await new Promise((r) => setTimeout(r, 1000));
          }
        } catch (err) {
          console.error("Hardware cycle failed:", err);
          setCameraError(err.message || 'Camera/microphone access failed.');
          if (stream) {
            stream.getTracks().forEach(t => t.stop());
            activeStream = null;
          }
          await new Promise((r) => setTimeout(r, 5000));
        }
      }
    };

    cycleHardware();

    return () => {
      isMounted = false;
      if (activeStream) {
        activeStream.getTracks().forEach(t => t.stop());
      }
      if (videoNode && videoNode.srcObject) {
        videoNode.srcObject.getTracks().forEach(t => t.stop());
      }
    };
  }, [token, userId, onSessionExpired, quickFaceCheck]);

  const scoreColor = (v) => (v > 75 ? 'text-emerald-600' : v >= 30 ? 'text-amber-600' : 'text-red-600');

  return (
    <div className="mb-6 p-6 bg-white border border-slate-200 rounded-2xl shadow-sm">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center space-x-5">
          <div className="w-16 h-16 rounded-xl bg-slate-900 overflow-hidden relative flex items-center justify-center border-2 border-slate-100 shadow-inner">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`w-full h-full object-cover transform scale-x-[-1] ${hardwareState === 'Recording' ? 'block' : 'hidden'}`}
            />
            {hardwareState !== 'Recording' && (
              <div className="w-full h-full flex items-center justify-center bg-slate-800">
                <svg className="w-6 h-6 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"></path>
                </svg>
              </div>
            )}
            {hardwareState === 'Recording' && (
              <div className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
            )}
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className={`w-2.5 h-2.5 rounded-full ${hardwareState === 'Recording' ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`}></span>
              <p className="text-sm font-black text-slate-900 tracking-tight">Zero-Trust Guard</p>
            </div>
            <p className="text-xs font-medium text-slate-500 mb-0.5">Risk Status: <span className="font-bold text-slate-700">{riskLevel}</span></p>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Hardware: {hardwareState} ({timer}s)
            </p>
            {cameraError && (
              <p className="text-[10px] font-bold text-red-500 mt-0.5">Camera error: {cameraError}</p>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Final Trust Score</p>
          <p className={`text-4xl font-black ${scoreColor(scores.trust)}`}>
            {scores.trust.toFixed(1)}%
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 border-t border-slate-100 pt-4">
        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Face Verification (30%)</p>
          <p className="text-xl font-black text-slate-800">{scores.faceVerification.toFixed(1)}%</p>
        </div>
        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Deepfake Detection (30%)</p>
          <p className="text-xl font-black text-slate-800">{scores.deepfakeDetection.toFixed(1)}%</p>
        </div>
        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Voice Spoof Detection (20%)</p>
          <p className="text-xl font-black text-slate-800">{scores.voiceSpoof.toFixed(1)}%</p>
        </div>
        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Behavioral Biometrics (20%)</p>
          <p className="text-xl font-black text-slate-800">{scores.behavioral.toFixed(1)}%</p>
        </div>
      </div>
    </div>
  );
}