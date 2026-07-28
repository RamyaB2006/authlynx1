import { useState } from 'react';
import Register from './components/Register';
import Login from './components/Login';
import Dashboard from './components/Dashboard';

export default function App() {
  const [view, setView] = useState('login');
  const [authData, setAuthData] = useState(null);

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4 sm:px-6 lg:px-8">
      {authData ? (
        <Dashboard authData={authData} onLogout={() => setAuthData(null)} />
      ) : (
        <div className="max-w-md mx-auto">
          <div className="text-center mb-10">
            <h1 className="text-4xl font-extrabold text-blue-900 tracking-tight mb-2">AuthLynx</h1>
            <p className="text-slate-500 text-sm font-medium">Continuous Zero-Trust Banking Identity</p>
          </div>

          <div className="flex bg-slate-200/60 rounded-xl p-1.5 mb-8 shadow-inner">
            <button 
              onClick={() => setView('login')} 
              className={`flex-1 py-2.5 text-sm rounded-lg font-bold transition-all ${
                view === 'login' ? 'bg-white text-blue-700 shadow-sm ring-1 ring-black/5' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Sign In
            </button>
            <button 
              onClick={() => setView('register')} 
              className={`flex-1 py-2.5 text-sm rounded-lg font-bold transition-all ${
                view === 'register' ? 'bg-white text-blue-700 shadow-sm ring-1 ring-black/5' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Create Account
            </button>
          </div>

          {view === 'register' && <Register onComplete={() => setView('login')} />}
          {view === 'login' && <Login onLoginSuccess={(data) => setAuthData(data)} />}
        </div>
      )}
    </div>
  );
}