const socket = io({ transports: ['websocket', 'polling'] });
let currentLang = 'en';
let mySid = null;
let currentRole = null;
let currentRoom = null;

function playBuzzSound() {
  try {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(440, audioCtx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(160, audioCtx.currentTime + 0.35);
    gain.gain.setValueAtTime(0.7, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.35);
  } catch(e) {}
}

function setLanguage(lang) {
  currentLang = lang;
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (translations[lang] && translations[lang][key]) {
      if (el.tagName === 'INPUT') el.placeholder = translations[lang][key];
      else el.innerText = translations[lang][key];
    }
  });
}

function switchView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = document.getElementById(viewId);
  if (target) target.classList.add('active');
}

window.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  const roomParam = urlParams.get('room');
  if (roomParam) {
    document.getElementById('roomInput').value = roomParam;
    switchView('playerJoinView');
  }
  setLanguage('en');

  // Attach button event listeners
  document.getElementById('hostSelectBtn').onclick = () => {
    currentRole = 'host';
    socket.emit('create_room');
  };

  document.getElementById('playerSelectBtn').onclick = () => {
    currentRole = 'player';
    switchView('playerJoinView');
  };

  document.getElementById('joinRoomBtn').onclick = () => {
    const room = document.getElementById('roomInput').value.trim();
    const name = document.getElementById('nameInput').value.trim();
    if (!room) return;
    socket.emit('join_room', { room, name });
  };

  const buzzer = document.getElementById('mainBuzzer');
  buzzer.onclick = () => {
    if (buzzer.classList.contains('red')) {
      socket.emit('buzz');
    }
  };

  document.getElementById('nextQBtn').onclick = () => socket.emit('next_question');
  document.getElementById('newTopicBtn').onclick = () => socket.emit('new_topic');
  document.getElementById('newGameBtn').onclick = () => {
    if (confirm(translations[currentLang].confirmNewGame)) {
      socket.emit('reset_game');
    }
  };

  document.querySelectorAll('.mult-btn').forEach(btn => {
    btn.onclick = () => {
      socket.emit('set_multiplier', { index: parseInt(btn.dataset.idx) });
    };
  });

  document.getElementById('shareLinkBtn').onclick = () => {
    const link = `${window.location.origin}/?room=${currentRoom}`;
    navigator.clipboard.writeText(link).then(() => {
      alert(translations[currentLang].linkCopied);
    });
  };
});

// Socket Events
socket.on('connect', () => { 
  mySid = socket.id; 
});

socket.on('room_created', data => {
  currentRoom = data.code;
  document.getElementById('hostRoomCode').innerText = data.code;
  switchView('hostView');
});

socket.on('joined_success', data => {
  currentRoom = data.room;
  document.getElementById('playerRoomCode').innerText = data.room;
  document.getElementById('playerGreeting').innerText = data.name;
  switchView('playerBuzzerView');
});

socket.on('join_error', data => alert(data.msg));

socket.on('player_buzzed', () => {
  playBuzzSound();
});

socket.on('room_state', state => {
  if (currentRole === 'host') {
    renderHostState(state);
  } else if (currentRole === 'player') {
    renderPlayerState(state);
  }
});

function renderHostState(state) {
  document.getElementById('hostQuestionVal').innerText = state.question_point;

  document.querySelectorAll('.mult-btn').forEach((b, idx) => {
    b.classList.toggle('active', idx === state.multiplier_idx);
  });

  const list = document.getElementById('playersList');
  list.innerHTML = '';
  
  if (state.players.length === 0) {
    list.innerHTML = `<p style="text-align:center;color:#888;">${translations[currentLang].noPlayers}</p>`;
    return;
  }

  state.players.forEach(p => {
    const isBuzzed = state.current_buzzer === p.sid;
    const row = document.createElement('div');
    row.className = `player-row ${isBuzzed ? 'buzzed' : ''}`;
    row.innerHTML = `
      <div class="p-name" style="background:${p.color}">${p.name}</div>
      <div class="p-score" style="background:${p.color}">${p.score}</div>
      <button class="score-control btn-minus" onclick="verdict(false)">–</button>
      <button class="score-control btn-plus" onclick="verdict(true)">+</button>
    `;
    list.appendChild(row);
  });
}

function renderPlayerState(state) {
  const buzzer = document.getElementById('mainBuzzer');
  const isMe = state.current_buzzer === mySid;
  const isDisqualified = state.disqualified.includes(mySid);

  if (isMe) {
    setBuzzer(buzzer, 'orange', 'buzzedWait');
  } else if (!state.buzzer_active || state.current_buzzer !== null) {
    setBuzzer(buzzer, 'grey', 'waitingHost');
  } else if (isDisqualified) {
    setBuzzer(buzzer, 'grey', 'lockedOut');
  } else {
    setBuzzer(buzzer, 'red', 'canBuzz');
  }
}

function setBuzzer(buzzer, stateClass, labelKey) {
  buzzer.className = `buzzer-btn ${stateClass}`;
  document.getElementById('buzzerStatusText').innerText = translations[currentLang][labelKey];
}

window.verdict = function(isCorrect) {
  socket.emit('answer_verdict', { correct: isCorrect });
};
