import { Routes, Route, Link } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import CardDetail from './pages/CardDetail.jsx'
import './App.css'

function App() {
  return (
    <>
      <nav className="nav">
        <Link to="/"><h1>eBay Price Tracker</h1></Link>
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cards/:cardQuery" element={<CardDetail />} />
      </Routes>
    </>
  )
}

export default App
