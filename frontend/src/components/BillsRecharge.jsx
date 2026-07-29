import { useEffect, useState } from 'react';
import axios from 'axios';

export default function BillsRecharge({ userId, accounts }) {
  const [billers, setBillers] = useState({});
  const [category, setCategory] = useState('');
  const [billerName, setBillerName] = useState('');
  const [consumerNumber, setConsumerNumber] = useState('');
  const [amount, setAmount] = useState('');
  const [fromAccount, setFromAccount] = useState('');
  const [message, setMessage] = useState({ text: '', type: '' });
  const [paying, setPaying] = useState(false);

  useEffect(() => {
    axios.get('http://127.0.0.1:8000/billers').then((res) => {
      setBillers(res.data);
      const firstCategory = Object.keys(res.data)[0];
      if (firstCategory) {
        setCategory(firstCategory);
        setBillerName(res.data[firstCategory][0]);
      }
    });
  }, []);

  const selectedFromAccount = fromAccount || accounts[0]?.account_number || '';

  const handleCategoryChange = (cat) => {
    setCategory(cat);
    setBillerName(billers[cat]?.[0] || '');
  };

  const handlePay = async (e) => {
    e.preventDefault();
    setMessage({ text: '', type: '' });
    setPaying(true);
    try {
      const res = await axios.post('http://127.0.0.1:8000/bills/pay', {
        user_id: userId,
        from_account: selectedFromAccount,
        biller_category: category,
        biller_name: billerName,
        consumer_number: consumerNumber,
        amount: parseFloat(amount),
      });
      setMessage({ text: res.data.message, type: 'success' });
      setConsumerNumber('');
      setAmount('');
    } catch (err) {
      setMessage({ text: err.response?.data?.detail || 'Payment failed', type: 'error' });
    } finally {
      setPaying(false);
    }
  };

  const isRecharge = category === 'Mobile Recharge';

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <h3 className="text-xl font-bold text-slate-900 mb-6">Bill Payments & Recharge</h3>

      <div className="flex flex-wrap gap-2 mb-6">
        {Object.keys(billers).map((cat) => (
          <button
            key={cat}
            onClick={() => handleCategoryChange(cat)}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition-colors cursor-pointer ${
              category === cat ? 'bg-blue-600 text-white shadow-md' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      <form onSubmit={handlePay} className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Biller</label>
          <select
            value={billerName} onChange={(e) => setBillerName(e.target.value)}
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {(billers[category] || []).map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
            {isRecharge ? 'Mobile Number' : 'Consumer / Account Number'}
          </label>
          <input
            type="text" required value={consumerNumber} onChange={(e) => setConsumerNumber(e.target.value)}
            placeholder={isRecharge ? 'e.g. 9876543210' : 'e.g. 100234567'}
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
          />
        </div>
        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Pay From</label>
          <select
            value={selectedFromAccount} onChange={(e) => setFromAccount(e.target.value)}
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((acc) => (
              <option key={acc.id} value={acc.account_number}>{acc.account_type}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Amount (₹)</label>
          <input
            type="number" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="w-full p-3.5 bg-slate-50 border border-slate-200 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
          />
        </div>
        <button
          type="submit" disabled={paying}
          className="md:col-span-2 py-3.5 bg-blue-600 hover:bg-blue-700 transition-colors rounded-xl font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 cursor-pointer"
        >
          {paying ? 'Processing...' : isRecharge ? 'Recharge Now' : 'Pay Bill'}
        </button>
      </form>

      {message.text && (
        <div className={`mt-5 p-4 rounded-xl text-sm font-bold border ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}