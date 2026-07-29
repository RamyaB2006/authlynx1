import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';

export default function Profile({ userId }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ email: '', phone: '', address: '' });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState({ text: '', type: '' });

  const fetchProfile = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8000/profile', { params: { user_id: userId } });
      setProfile(res.data);
      setForm({
        email: res.data.email || '',
        phone: res.data.phone || '',
        address: res.data.address || '',
      });
    } catch (err) {
      console.error('Error fetching profile:', err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
  const timer = setTimeout(() => {
    fetchProfile();
  }, 0);
  return () => clearTimeout(timer);
}, [fetchProfile]);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMessage({ text: '', type: '' });
    try {
      await axios.put('http://127.0.0.1:8000/profile', { user_id: userId, ...form });
      setMessage({ text: 'Profile updated successfully', type: 'success' });
      setEditing(false);
      fetchProfile();
    } catch (err) {
      setMessage({ text: err.response?.data?.detail || 'Failed to update profile', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  if (loading || !profile) {
    return (
      <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
        <p className="text-sm text-slate-500 font-medium py-8 text-center">Loading profile...</p>
      </div>
    );
  }

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-bold text-slate-900">Profile & Settings</h3>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-sm text-white shadow-lg shadow-blue-600/20 cursor-pointer"
          >
            Edit Details
          </button>
        )}
      </div>

      <div className="flex items-center space-x-4 mb-8 pb-6 border-b border-slate-100">
        <div className="w-16 h-16 rounded-2xl bg-blue-900 text-white flex items-center justify-center text-2xl font-black">
          {profile.full_name?.charAt(0).toUpperCase()}
        </div>
        <div>
          <p className="text-lg font-black text-slate-900">{profile.full_name}</p>
          <p className="text-sm font-medium text-slate-500">Customer ID: {profile.customer_id}</p>
        </div>
      </div>

      {editing ? (
        <form onSubmit={handleSave} className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Email Address</label>
            <input
              type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="you@example.com"
              className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
            />
          </div>
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Phone Number</label>
            <input
              type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="+91 98765 43210"
              className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Address</label>
            <textarea
              rows={3} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })}
              placeholder="Street, City, State, PIN Code"
              className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400 resize-none"
            />
          </div>
          <div className="md:col-span-2 flex space-x-3">
            <button
              type="submit" disabled={saving}
              className="flex-1 py-3.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 cursor-pointer"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              type="button" onClick={() => setEditing(false)}
              className="flex-1 py-3.5 bg-white hover:bg-slate-50 border border-slate-200 transition-colors rounded-xl font-bold text-slate-700 cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Email Address</p>
            <p className="text-sm font-bold text-slate-800">{profile.email || 'Not set'}</p>
          </div>
          <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Phone Number</p>
            <p className="text-sm font-bold text-slate-800">{profile.phone || 'Not set'}</p>
          </div>
          <div className="md:col-span-2 p-4 bg-slate-50 rounded-xl border border-slate-200">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Address</p>
            <p className="text-sm font-bold text-slate-800">{profile.address || 'Not set'}</p>
          </div>
        </div>
      )}

      {message.text && (
        <div className={`mt-5 p-4 rounded-xl text-sm font-bold border ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}