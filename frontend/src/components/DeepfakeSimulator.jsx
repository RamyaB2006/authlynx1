import { useState } from 'react';
import axios from 'axios';

export default function DeepfakeSimulator({ onSessionExpired }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const handleSimulate = async () => {
    if (!selectedFile) {
      alert("Please select a media file first.");
      return;
    }

    setLoading(true);
    setResult(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await axios.post('http://127.0.0.1:8000/simulate-attack', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      setResult(response.data);

      // If classified as a deepfake, trigger session termination sequence
      if (response.data.is_active === false) {
        setTimeout(() => {
          alert(`🚨 SECURITY BREACH: ${response.data.message}\nFake Confidence: ${response.data.fake_percentage}%`);
          localStorage.removeItem('token'); 
          if (onSessionExpired) onSessionExpired();
        }, 2000);
      }

    } catch (error) {
      console.error("Simulation failed", error);
      alert("Error communicating with the AI Engine.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 bg-white border border-slate-200 rounded-2xl shadow-sm mb-6">
      <h3 className="text-lg font-bold text-slate-800 mb-1">Deepfake Attack Simulator </h3>
      <p className="text-sm text-slate-500 mb-4">
        Upload any media file (image or audio) to test the AI classification engine and check real vs. fake confidence scores.
      </p>
      
      <div className="flex flex-col space-y-4">
        <input 
          type="file" 
          onChange={(e) => setSelectedFile(e.target.files[0])}
          className="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
        />
        
        <button 
          onClick={handleSimulate}
          disabled={loading || !selectedFile}
          className="w-full py-3 bg-slate-900 text-white rounded-xl font-bold hover:bg-slate-800 disabled:opacity-50 transition-colors shadow-md"
        >
          {loading ? 'Analyzing Media Features...' : 'Launch Simulated Attack'}
        </button>

        {result && (
          <div className={`mt-4 p-4 rounded-xl border ${
            result.classification === 'fake' ? 'bg-red-50 border-red-200 text-red-900'
            : result.classification === 'inconclusive' ? 'bg-amber-50 border-amber-200 text-amber-900'
            : 'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}>
            <p className="font-extrabold uppercase text-xs tracking-wider mb-2">
              Classification Result: {result.classification.toUpperCase()}
            </p>
            <div className="space-y-1 text-sm font-medium">
              <p>🟢 Real Confidence: <span className="font-bold">{result.real_percentage}%</span></p>
              <p>🔴 Fake/Spoof Confidence: <span className="font-bold">{result.fake_percentage}%</span></p>
            </div>
            <p className="text-xs mt-3 font-semibold">{result.message}</p>
            {result.debug_signals?.note && (
              <p className="text-[10px] mt-2 font-mono opacity-70">debug: {result.debug_signals.note}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}