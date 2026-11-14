import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { ReelPicks } from './components/ReelPicks';

createRoot(document.getElementById('root')!).render(<StrictMode><ReelPicks /></StrictMode>);
navigator.serviceWorker?.register('sw.js');
