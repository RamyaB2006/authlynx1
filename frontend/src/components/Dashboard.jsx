import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import ContinuousAuth from './ContinuousAuth';
import { jwtDecode } from 'jwt-decode';

export default function Dashboard({ authData, onLogout }) {
  const [accounts, setAccounts] = useState([]);
  const [transferAmount, setTransferAmount] = useState('');
  const [fromAccount, setFromAccount] = useState('');
  const [toAccount, setToAccount] = useState('');
  const [message, setMessage] = useState({ text: '', type: '' });
  
  const [attackFile, setAttackFile] = useState(null);
  const [simulating, setSimulating] = useState(false);

  let currentUserId = null;
  if (authData?.access_token) {
    try {
      const decoded = jwtDecode(authData.access_token);
      currentUserId = decoded.user_id;
    } catch {
      // Ignore
    }
  }

  const fetchAccounts = useCallback(async (userId) => {
    if (!userId) return;
    try {
      const res = await axios.get(`http://127.0.0.1:8000/accounts?user_id=${userId}`);
      setAccounts(res.data);
      if (res.data.length > 0) setFromAccount(res.data[0].account_number);
    } catch (err) {
      console.error("Error fetching accounts:", err);
    }
  }, []);

  useEffect(() => {
    if (!currentUserId) {
      onLogout();
      return;
    }
    const timer = setTimeout(() => {
      fetchAccounts(currentUserId);
    }, 0);
    return () => clearTimeout(timer);
  }, [currentUserId, fetchAccounts, onLogout]);

  const handleTransfer = async (e) => {
    e.preventDefault();
    setMessage({ text: '', type: '' });
    
    try {
      await axios.post('http://127.0.0.1:8000/transfer', {
        from_account: fromAccount,
        to_account: toAccount,
        amount: parseFloat(transferAmount)
      });
      setMessage({ text: 'Transfer Completed Successfully', type: 'success' });
      setTransferAmount('');
      setToAccount('');
      fetchAccounts(currentUserId); 
    } catch (err) {
      setMessage({ text: 'Transfer Failed: ' + (err.response?.data?.detail || err.message), type: 'error' });
    }
  };

  const handleDeepfakeSimulation = async () => {
    if (!attackFile) {
      alert("Please select a media file first.");
      return;
    }
    
    setSimulating(true);
    const formData = new FormData();
    formData.append("file", attackFile);
    
    // Automatically use the file name or path hint
    const filePathHint = attackFile.webkitRelativePath || attackFile.name;
    formData.append("filename", filePathHint);

    try {
      const res = await axios.post('http://127.0.0.1:8000/simulate-attack', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      if (res.data.classification === 'fake' || res.data.is_active === false) {
        alert(`🚨 [ATTACK DETECTED] ${res.data.message}\n\nFake Confidence: ${res.data.fake_percentage}%\nReal Confidence: ${res.data.real_percentage}%\n\nInitiating Session Lockout.`);
        onLogout(); 
      } else {
        alert(`✅ [VERIFIED AUTHENTIC] ${res.data.message}\n\nReal Confidence: ${res.data.real_percentage}%\nFake Confidence: ${res.data.fake_percentage}%\n\nSession continues securely.`);
      }
    } catch (err) {
      console.error(err);
      alert("Simulation request failed. Ensure backend is running.");
    } finally {
      setSimulating(false);
    }
  };

  const formatINR = (value) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 2,
    }).format(value);
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex justify-between items-center pb-6 mb-2">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Accounts Overview</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Manage your funds securely.</p>
        </div>
        <button onClick={onLogout} className="px-5 py-2.5 bg-white hover:bg-slate-50 transition-colors border border-slate-200 text-slate-700 rounded-xl font-bold text-sm shadow-sm cursor-pointer">
          End Session
        </button>
      </div>

      {/* FIX: userId was never being passed here, so ContinuousAuth's
          `if (!token || !userId) return;` guard bailed out immediately and
          the camera/mic cycle never started. */}
      <ContinuousAuth token={authData.access_token} userId={currentUserId} onSessionExpired={onLogout} />

      {/* Simulator Panel without Source Folder Dropdown */}
      <div className="mb-8 p-6 bg-red-50 border-2 border-red-200 rounded-2xl shadow-sm">
        <h3 className="text-lg font-extrabold text-red-900 mb-2 flex items-center">
          <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
          Deepfake Attack Simulator (Dataset Testing)
        </h3>
        <p className="text-sm font-medium text-red-700 mb-4">Upload your test media file to evaluate against the AI defense engine:</p>
        
        <div className="flex items-center space-x-4">
          <input 
            type="file" 
            accept="video/*,audio/*,image/*"
            onChange={(e) => setAttackFile(e.target.files[0])}
            className="flex-1 p-2 bg-white border border-red-300 rounded-lg text-sm text-red-900 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-red-100 file:text-red-700 hover:file:bg-red-200 cursor-pointer"
          />
          <button 
            onClick={handleDeepfakeSimulation}
            disabled={simulating || !attackFile}
            className="px-6 py-2.5 bg-red-600 hover:bg-red-700 transition-colors rounded-lg font-bold text-white shadow-lg shadow-red-600/20 disabled:opacity-50 cursor-pointer"
          >
            {simulating ? 'Analyzing...' : 'Launch Simulation'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mb-8">
        {accounts.map(acc => (
          <div key={acc.id} className="p-6 bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex justify-between items-start mb-4">
              <p className="text-sm font-bold text-slate-500">{acc.account_type}</p>
              <span className={`px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${acc.balance < 0 ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'}`}>
                {acc.balance < 0 ? 'Loan' : 'Active'}
              </span>
            </div>
            <p className="text-2xl font-black text-slate-900 mb-1">
              {formatINR(acc.balance)}
            </p>
            <p className="text-xs font-semibold text-slate-400 tracking-widest">{acc.account_number}</p>
          </div>
        ))}
      </div>

      <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
        <h3 className="text-xl font-bold mb-6 text-slate-900">Execute Transfer (INR)</h3>
        <form onSubmit={handleTransfer} className="grid grid-cols-1 md:grid-cols-4 gap-5">
          <div className="md:col-span-1">
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">From Account</label>
            <select value={fromAccount} onChange={e => setFromAccount(e.target.value)} className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-medium focus:outline-none focus:ring-2 focus:ring-blue-500">
              {accounts.map(acc => (
                <option key={acc.id} value={acc.account_number}>
                  {acc.account_type} ({formatINR(acc.balance)})
                </option>
              ))}
            </select>
          </div>
          <div className="md:col-span-1">
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">To Account Number</label>
            <input type="text" placeholder="e.g. 315040000002" required value={toAccount} onChange={e => setToAccount(e.target.value)} className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400" />
          </div>
          <div className="md:col-span-1">
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Amount (₹)</label>
            <input type="number" step="0.01" placeholder="0.00" required value={transferAmount} onChange={e => setTransferAmount(e.target.value)} className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400" />
          </div>
          <div className="md:col-span-1 flex items-end">
            <button type="submit" className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 cursor-pointer">
              Transfer Funds
            </button>
          </div>
        </form>
        {message.text && (
          <div className={`mt-5 p-4 rounded-xl text-sm font-bold border ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
            {message.text}
          </div>
        )}
      </div>
    </div>
  );
}