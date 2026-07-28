import { useEffect, useRef, useState, useCallback } from 'react';
import axios from 'axios';

export default function ContinuousAuth({ token, onSessionExpired }) {
  const [trustScore, setTrustScore] = useState(91.5);
  const [riskLevel, setRiskLevel] = useState('Low (Secure)');
  const [isMonitoring, setIsMonitoring] = useState(true);

  const videoRef = useRef(null);
  const streamRef = useRef(null);

  // Behavioral metrics tracker
  const metricsRef = useRef({
    typingSpeed: 120,
    holdTime: 85,
    latency: 45,
    rhythm: 0.92,
    errorRate: 1.2,
    movement_speed: 1.5,
    clickFrequency: 0.5,
    scrollingSpeed: 10
  });

  const captureAndVerify = useCallback(async () => {
    if (!isMonitoring || !token) return;

    try {
      const video = videoRef.current;
      if (!video || video.videoWidth === 0 || video.videoHeight === 0) return;

      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      const frameBlob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8));
      if (!frameBlob) return;

      const formData = new FormData();
      formData.append('token', token);
      formData.append('frame', frameBlob, 'frame.jpg');
      formData.append('typing_speed', metricsRef.current.typingSpeed);
      formData.append('hold_time', metricsRef.current.holdTime);
      formData.append('latency', metricsRef.current.latency);
      formData.append('rhythm', metricsRef.current.rhythm);
      formData.append('error_rate', metricsRef.current.errorRate);
      formData.append('movement_speed', metricsRef.current.movement_speed);
      formData.append('click_frequency', metricsRef.current.clickFrequency);
      formData.append('scrolling_speed', metricsRef.current.scrollingSpeed);

      const res = await axios.post('http://127.0.0.1:8000/verify-session', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      setTrustScore(res.data.trust_score);
      setRiskLevel(res.data.risk_level);

      if (!res.data.is_active || res.data.trust_score <= 30) {
        setIsMonitoring(false);
        alert(`🚨 [SECURITY LOCKOUT] Trust score dropped to ${res.data.trust_score} (${res.data.risk_level}). Terminating session.`);
        onSessionExpired();
      }
    } catch (err) {
      console.error("Continuous auth check failed:", err);
    }
  }, [token, isMonitoring, onSessionExpired]);

  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: true })
      .then((stream) => {
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      })
      .catch((err) => console.warn("Camera preview warning:", err));

    const interval = setInterval(captureAndVerify, 5000);

    return () => {
      clearInterval(interval);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, [captureAndVerify]);

  return (
    <div className="mb-6 p-4 bg-white border border-slate-200 rounded-2xl shadow-sm flex items-center justify-between">
      <div className="flex items-center space-x-4">
        <div className="w-12 h-12 rounded-xl bg-slate-900 overflow-hidden relative flex items-center justify-center">
          <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover transform scale-x-[-1]" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            <p className="text-sm font-black text-slate-900 tracking-tight">Zero-Trust Continuous Guard Active</p>
          </div>
          <p className="text-xs font-medium text-slate-500">Risk Status: <span className="font-bold text-slate-700">{riskLevel}</span></p>
        </div>
      </div>

      <div className="text-right">
        <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Trust Score</p>
        <p className={`text-2xl font-black ${trustScore > 70 ? 'text-emerald-600' : trustScore >= 30 ? 'text-amber-600' : 'text-red-600'}`}>
          {trustScore.toFixed(1)}%
        </p>
      </div>
    </div>
  );
}