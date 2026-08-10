import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { inferInitialLocale } from './locale'

// Apply saved theme immediately before render; default to dark
const savedTheme = localStorage.getItem('theme')
if (savedTheme === 'light') {
  document.documentElement.setAttribute('data-theme', 'light')
} else {
  document.documentElement.setAttribute('data-theme', 'dark')
}
const savedLocale = inferInitialLocale()
document.documentElement.lang = savedLocale === 'zh' ? 'zh-CN' : 'en'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
