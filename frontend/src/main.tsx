import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AppStateProvider } from './context/AppStateContext.tsx'
import { ThemeProvider } from './context/ThemeContext.tsx'
import { ChatProvider } from './context/ChatContext.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AppStateProvider>
          <ChatProvider>
            <App />
          </ChatProvider>
        </AppStateProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
