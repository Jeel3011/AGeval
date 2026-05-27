'use client';
import { createContext, useContext, useState, ReactNode } from 'react';

type ToastType = 'info' | 'success' | 'error';
type Toast = { id: number; message: string; type: ToastType };

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (message: string, type: ToastType = 'info') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, type === 'error' ? 6000 : 3500);
  };

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>
            <span>{t.message}</span>
            <button 
              style={{background:'none',border:'none',color:'inherit',opacity:0.7,cursor:'pointer',marginLeft:12,padding:0,fontSize:14}}
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
            >✕</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast outside Provider');
  return ctx;
}
