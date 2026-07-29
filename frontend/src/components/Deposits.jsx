import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { formatINR, formatDate } from '../utils/format';

export default function Deposits({ userId, accounts }) {
  const [deposits, setDeposits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [message, setMessage] = useState({ text: '', type: '' });
  const [depositType, setDepositType] = useState('Fixed');
  const [principal, setPrincipal] = useState('');
  const [tenure, setTenure] = useState('12');
  const [sourceAccount, setSourceAccount] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchDeposits = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8000/deposits', { params: { user_id: userId } });
      setDeposits(res.data);
    } catch (err) {
      console.error('Error fetching deposits:', err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchDeposits();
    }, 0);
    return () => clearTimeout(timer);
  }, [fetchDeposits]);

  const selectedSourceAccount = sourceAccount || accounts[0]?.account_number || '';

  const handleCreate = async (e) => {
    e.preventDefault();
    setMessage({ text: '', type: '' });
    setSubmitting(true);
    try {
      await axios.post('http://127.0.0.1:8000/deposits', {
        user_id: userId,
        source_account: selectedSourceAccount,
        deposit_type: depositType,
        principal_amount: parseFloat(principal),
        tenure_months: parseInt(tenure, 10),
      });
      setMessage({ text: `${depositType} Deposit opened successfully`, type: 'success' });
      setPrincipal('');
      setShowForm(false);
      fetchDeposits();
    } catch (err) {
      setMessage({ text: err.response?.data?.detail || 'Failed to open deposit', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const statusColor = (status) =>
    status === 'Active' ? 'bg-emerald-50 text-emerald-600' : status === 'Matured' ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-500';

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-bold text-slate-900">Fixed & Recurring Deposits</h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-sm text-white shadow-lg shadow-blue-600/20 cursor-pointer"
        >
          {showForm ? 'Cancel' : '+ Open New Deposit'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6 p-5 bg-slate-50 rounded-xl border border-slate-200">
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Deposit Type</label>
            <select
              value={depositType} onChange={(e) => setDepositType(e.target.value)}
              className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="Fixed">Fixed Deposit (6.75% p.a.)</option>
              <option value="Recurring">Recurring Deposit (6.25% p.a.)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Source Account</label>
            <select
              value={selectedSourceAccount} onChange={(e) => setSourceAccount(e.target.value)}
              className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.account_number}>{acc.account_type} ({formatINR(acc.balance)})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              {depositType === 'Recurring' ? 'Monthly Installment (₹)' : 'Principal Amount (₹)'}
            </label>
            <input
              type="number" step="0.01" required value={principal} onChange={(e) => setPrincipal(e.target.value)}
              placeholder="0.00"
              className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
            />
          </div>
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Tenure (months)</label>
            <input
              type="number" min="1" required value={tenure} onChange={(e) => setTenure(e.target.value)}
              className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit" disabled={submitting}
            className="md:col-span-2 py-3 bg-slate-900 hover:bg-slate-800 transition-colors rounded-xl font-bold text-white disabled:opacity-50 cursor-pointer"
          >
            {submitting ? 'Opening...' : 'Open Deposit'}
          </button>
        </form>
      )}

      {message.text && (
        <div className={`mb-5 p-3.5 rounded-xl text-sm font-bold border ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
          {message.text}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">Loading...</p>
      ) : deposits.length === 0 ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">No deposits opened yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {deposits.map((d) => (
            <div key={d.id} className="p-5 bg-slate-50 rounded-xl border border-slate-200">
              <div className="flex justify-between items-start mb-3">
                <p className="text-sm font-bold text-slate-800">{d.deposit_type} Deposit</p>
                <span className={`px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${statusColor(d.status)}`}>
                  {d.status}
                </span>
              </div>
              <p className="text-xl font-black text-slate-900 mb-1">{formatINR(d.principal_amount)}</p>
              <p className="text-xs font-semibold text-slate-500 mb-3">@ {d.interest_rate}% p.a. · {d.tenure_months} months</p>
              <div className="flex justify-between text-xs font-medium text-slate-400 border-t border-slate-200 pt-3">
                <span>Maturity: {formatDate(d.maturity_date)}</span>
                <span className="font-bold text-emerald-600">{formatINR(d.maturity_amount)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}