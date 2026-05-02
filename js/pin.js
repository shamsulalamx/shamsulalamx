
/* ============================================================
   PIN.JS — 4-digit passcode protection
============================================================ */
const PIN = (() => {
  const STORAGE_KEY = 'nbme_pin_v1';
  let _buffer = '';
  let _mode = 'enter'; // 'enter' | 'setup' | 'confirm'
  let _firstPin = '';

  function getStored() {
    return localStorage.getItem(STORAGE_KEY) || null;
  }
  function setStored(pin) {
    localStorage.setItem(STORAGE_KEY, pin);
  }

  function init() {
    const stored = getStored();
    const screen = document.getElementById('pin-screen');
    if (!stored) {
      // First launch — setup mode
      _mode = 'setup';
      document.getElementById('pin-subtitle').textContent = 'Create a 4-digit PIN';
      document.getElementById('pin-setup-hint').textContent = 'You will be asked to confirm your PIN.';
      screen.style.display = 'flex';
    } else {
      // Normal entry mode
      _mode = 'enter';
      document.getElementById('pin-subtitle').textContent = 'Enter your 4-digit PIN';
      document.getElementById('pin-setup-hint').textContent = '';
      screen.style.display = 'flex';
    }
    // Keyboard support
    document.addEventListener('keydown', onKey);
  }

  function onKey(e) {
    const screen = document.getElementById('pin-screen');
    if (screen.style.display === 'none') return;
    if (e.key >= '0' && e.key <= '9') press(e.key);
    else if (e.key === 'Backspace') del();
    else if (e.key === 'Enter') enter();
  }

  function press(digit) {
    if (_buffer.length >= 4) return;
    _buffer += digit;
    updateDots();
    if (_buffer.length === 4) {
      setTimeout(enter, 120);
    }
  }

  function del() {
    _buffer = _buffer.slice(0, -1);
    updateDots();
    clearError();
  }

  function enter() {
    if (_buffer.length < 4) {
      showError('Enter all 4 digits');
      return;
    }

    if (_mode === 'setup') {
      _firstPin = _buffer;
      _buffer = '';
      _mode = 'confirm';
      document.getElementById('pin-subtitle').textContent = 'Confirm your PIN';
      document.getElementById('pin-setup-hint').textContent = 'Enter the same PIN again to confirm.';
      updateDots();
      return;
    }

    if (_mode === 'confirm') {
      if (_buffer === _firstPin) {
        setStored(_buffer);
        unlock();
      } else {
        shakeError('PINs do not match. Start over.');
        _buffer = ''; _firstPin = '';
        _mode = 'setup';
        document.getElementById('pin-subtitle').textContent = 'Create a 4-digit PIN';
        document.getElementById('pin-setup-hint').textContent = 'You will be asked to confirm your PIN.';
        updateDots();
      }
      return;
    }

    if (_mode === 'enter') {
      if (_buffer === getStored()) {
        unlock();
      } else {
        shakeError('Incorrect PIN. Try again.');
        _buffer = '';
        updateDots();
      }
    }
  }

  function unlock() {
    const screen = document.getElementById('pin-screen');
    screen.style.opacity = '0';
    screen.style.transition = 'opacity .3s';
    setTimeout(() => {
      screen.style.display = 'none';
      document.removeEventListener('keydown', onKey);
    }, 300);
    _buffer = '';
  }

  function updateDots() {
    for (let i = 0; i < 4; i++) {
      const dot = document.getElementById('pd' + i);
      if (!dot) continue;
      dot.classList.remove('error');
      dot.classList.toggle('filled', i < _buffer.length);
    }
  }

  function showError(msg) {
    document.getElementById('pin-error').textContent = msg;
  }

  function clearError() {
    document.getElementById('pin-error').textContent = '';
  }

  function shakeError(msg) {
    for (let i = 0; i < 4; i++) {
      const dot = document.getElementById('pd' + i);
      if (dot) dot.classList.add('error');
    }
    showError(msg);
    setTimeout(() => {
      for (let i = 0; i < 4; i++) {
        const dot = document.getElementById('pd' + i);
        if (dot) dot.classList.remove('error');
      }
    }, 600);
  }

  return { init, press, del, enter };
})();
window.PIN = PIN;

// ── Bootstrap ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  PIN.init();
  App.init();
});

