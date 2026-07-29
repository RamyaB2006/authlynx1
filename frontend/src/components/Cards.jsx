import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';

export default function Cards({ userId }) {
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actingOn, setActingOn] = useState(null);

  const fetchCards = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8000/cards', { params: { user_id: userId } });
      setCards(res.data);
    } catch (err) {
      console.error('Error fetching cards:', err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
  const timer = setTimeout(() => {
    fetchCards();
  }, 0);
  return () => clearTimeout(timer);
}, [fetchCards]);

  const handleAction = async (cardId, action) => {
    setActingOn(cardId);
    try {
      await axios.post('http://127.0.0.1:8000/cards/action', { user_id: userId, card_id: cardId, action });
      fetchCards();
    } catch (err) {
      console.error('Card action failed:', err);
    } finally {
      setActingOn(null);
    }
  };

  const statusStyles = {
    Active: 'from-blue-600 to-blue-800',
    Frozen: 'from-slate-400 to-slate-600',
    Blocked: 'from-red-500 to-red-700',
  };

  return (
    <div className="p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
      <h3 className="text-xl font-bold text-slate-900 mb-6">Cards Management</h3>

      {loading ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">Loading...</p>
      ) : cards.length === 0 ? (
        <p className="text-sm text-slate-500 font-medium py-8 text-center">No cards issued to this account yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {cards.map((c) => (
            <div key={c.id}>
              <div className={`relative p-6 rounded-2xl bg-linear-to-br ${statusStyles[c.status] || statusStyles.Active} text-white shadow-lg overflow-hidden`}>
                <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-10 -mt-10"></div>
                <p className="text-xs font-bold uppercase tracking-widest opacity-80 mb-6">IOB {c.card_type} Card</p>
                <p className="text-xl font-black tracking-[0.2em] mb-6">•••• •••• •••• {c.card_number_last4}</p>
                <div className="flex justify-between items-end">
                  <div>
                    <p className="text-[10px] font-bold uppercase opacity-70">Linked Account</p>
                    <p className="text-sm font-bold">{c.linked_account_number}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-bold uppercase opacity-70">Expires</p>
                    <p className="text-sm font-bold">{String(c.expiry_month).padStart(2, '0')}/{c.expiry_year}</p>
                  </div>
                </div>
                <p className="absolute top-6 right-6 text-sm font-black italic opacity-80">{c.card_network}</p>
              </div>

              <div className="flex items-center justify-between mt-3">
                <span className={`px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${
                  c.status === 'Active' ? 'bg-emerald-50 text-emerald-600' : c.status === 'Frozen' ? 'bg-amber-50 text-amber-600' : 'bg-red-50 text-red-600'
                }`}>
                  {c.status}
                </span>
                <div className="flex space-x-2">
                  {c.status !== 'Blocked' && (
                    <button
                      onClick={() => handleAction(c.id, c.status === 'Frozen' ? 'unfreeze' : 'freeze')}
                      disabled={actingOn === c.id}
                      className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      {c.status === 'Frozen' ? 'Unfreeze' : 'Freeze'}
                    </button>
                  )}
                  {c.status !== 'Blocked' && (
                    <button
                      onClick={() => handleAction(c.id, 'block')}
                      disabled={actingOn === c.id}
                      className="px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-bold transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      Block
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}