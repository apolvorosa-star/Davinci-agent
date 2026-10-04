// Componente principal App
import React from 'react';
import Header from './components/Header';
import Footer from './components/Footer';

const App = () => {
  return (
    <div className='App'>
      <Header />
      <main>
        <h2>Welcome to My App</h2>
        <p>This is a simple React application.</p>
      </main>
      <Footer />
    </div>
  );
};

export default App;