import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';

export default function Beneficiaries({ userId }) {
  const [beneficiaries, setBeneficiaries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [message, setMessage] = useState({ text: '', type: '' });
  const [form, setForm] = useState({ nickname: '', account_number: '', ifsc_code: '', bank_name: '' });

  const fetchBeneficiaries = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8000/beneficiaries', { params: { user_id: userId } });
      setBeneficiaries(res.data);
    } catch (err) {
      console.error('Error fetching beneficiaries:', err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
  const timer = setTimeout(() => {
    fetchBeneficiaries();
  }, 0);
  return () => clearTimeout(timer);
}, [fetchBeneficiaries]);
  const handleAdd = async (e) => {
    e.preventDefault();
    setMessage({ text: '', type: '' });
    try {
      await axios.post('http://127.0.0.1:8000/beneficiaries', { user_id: userId, ...form });
      setForm({ nickname: '', account_number: '', ifsc_code: '', bank_name: '' });
      setShowForm(false);
      fetchBeneficiaries();
      setMessage({ text: 'Beneficiary added successfully', type: 'success' });
    } catch (err) {
      setMessage({ text: err.response?.data?.detail || 'Failed to add beneficiary', type: 'error' });
    }
  };

  const handleDelete = async (id) => {
    try {
      await axios.delete(`http://127.0.0.1:8000/beneficiaries/${id}`, { params: { user_id: userId } });
      fetchBeneficiaries();
    } catch (err) {
      console.error('Error deleting beneficiary:', err);
    }
  };

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-bold text-slate-900">Manage Beneficiaries</h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-sm text-white shadow-lg shadow-blue-600/20 cursor-pointer"
        >
          {showForm ? 'Cancel' : '+ Add Beneficiary'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6 p-5 bg-slate-50 rounded-xl border border-slate-200">
          <input
            type="text" required placeholder="Nickname (e.g. Mom, Rent)"
            value={form.nickname} onChange={(e) => setForm({ ...form, nickname: e.target.value })}
            className="p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="text" required placeholder="Account Number"
            value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })}
            className="p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="text" required placeholder="IFSC Code"
            value={form.ifsc_code} onChange={(e) => setForm({ ...form, ifsc_code: e.target.value.toUpperCase() })}
            className="p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="text" required placeholder="Bank Name"
            value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })}
            className="p-3 bg-white border border-slate-200 rounded-xl text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button type="submit" className="md:col-span-2 py-3 bg-slate-900 hover:bg-slate-800 transition-colors rounded-xl font-bold text-white cursor-pointer">
            Save Beneficiary
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
      ) : beneficiaries.length === 0 ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">No saved beneficiaries yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {beneficiaries.map((b) => (
            <div key={b.id} className="p-4 bg-slate-50 rounded-xl border border-slate-200 flex justify-between items-start">
              <div>
                <p className="text-sm font-bold text-slate-800">{b.nickname}</p>
                <p className="text-xs font-medium text-slate-500 mt-0.5">{b.account_number}</p>
                <p className="text-xs font-medium text-slate-400">{b.bank_name} · {b.ifsc_code}</p>
              </div>
              <button
                onClick={() => handleDelete(b.id)}
                className="text-xs font-bold text-red-500 hover:text-red-700 cursor-pointer"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}