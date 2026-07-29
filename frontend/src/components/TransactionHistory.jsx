import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { formatINR, formatDate } from '../utils/format';

export default function TransactionHistory({ userId, accounts }) {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [accountFilter, setAccountFilter] = useState('all');

  const fetchTransactions = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const params = { user_id: userId, limit: 100 };
      if (accountFilter !== 'all') params.account_number = accountFilter;
      const res = await axios.get('http://127.0.0.1:8000/transactions', { params });
      setTransactions(res.data);
    } catch (err) {
      console.error('Error fetching transactions:', err);
    } finally {
      setLoading(false);
    }
  }, [userId, accountFilter]);

  useEffect(() => {
  const timer = setTimeout(() => {
    fetchTransactions();
  }, 0);
  return () => clearTimeout(timer);
  }, [fetchTransactions]);

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-bold text-slate-900">Transaction History</h3>
        <select
          value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value)}
          className="p-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Accounts</option>
          {accounts.map((acc) => (
            <option key={acc.id} value={acc.account_number}>
              {acc.account_type} ({acc.account_number})
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">Loading transactions...</p>
      ) : transactions.length === 0 ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">No transactions yet.</p>
      ) : (
        <div className="divide-y divide-slate-100">
          {transactions.map((t) => (
            <div key={t.id} className="flex items-center justify-between py-4">
              <div className="flex items-center space-x-4">
                <div
                  className={`w-10 h-10 rounded-xl flex items-center justify-center font-black text-sm ${
                    t.txn_type === 'credit' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'
                  }`}
                >
                  {t.txn_type === 'credit' ? '↓' : '↑'}
                </div>
                <div>
                  <p className="text-sm font-bold text-slate-800">{t.description}</p>
                  <p className="text-xs font-medium text-slate-400">
                    {t.category} · {t.account_number} · {formatDate(t.created_at)}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <p className={`text-sm font-black ${t.txn_type === 'credit' ? 'text-emerald-600' : 'text-red-600'}`}>
                  {t.txn_type === 'credit' ? '+' : '-'}{formatINR(t.amount)}
                </p>
                <p className="text-xs font-medium text-slate-400">Bal: {formatINR(t.balance_after)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}