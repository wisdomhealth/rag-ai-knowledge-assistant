'use strict';
const form = document.querySelector('#chat-form');
const input = document.querySelector('#question');
const messages = document.querySelector('#messages');
const statusText = document.querySelector('#status');
const send = document.querySelector('#send');
const stop = document.querySelector('#stop');
const newChat = document.querySelector('#new-chat');
let conversationId = null;
let controller = null;

function message(role, text) {
  document.querySelector('#welcome').hidden = true;
  const card = document.createElement('article');
  card.className = `message ${role}`;
  const title = document.createElement('h2');
  title.textContent = role === 'user' ? 'You' : 'Zhiku Assistant';
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = text;
  const note = document.createElement('div');
  note.className = 'note';
  card.append(title, body, note);
  messages.append(card);
  return {card, body, note};
}

function sources(card, items) {
  card.querySelector('.sources')?.remove();
  const group = document.createElement('div');
  group.className = 'sources';
  for (const source of items) {
    const detail = document.createElement('details');
    detail.className = 'source';
    const summary = document.createElement('summary');
    summary.textContent = `[${source.citation_id}] ${source.file_name} · ${source.page_number == null ? 'Page unknown' : `Page ${source.page_number}`}`;
    const snippet = document.createElement('p');
    snippet.textContent = source.snippet;
    detail.append(summary, snippet);
    try {
      const url = new URL(source.source_link);
      if (['https:', 'http:'].includes(url.protocol)) {
        const link = document.createElement('a');
        link.href = url.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'View source ↗';
        detail.append(link);
      }
    } catch (_) { /* Invalid or absent source URL: show text only. */ }
    group.append(detail);
  }
  card.append(group);
}

async function check(response) {
  if (response.ok) return response;
  const data = await response.json().catch(() => ({}));
  const detail = data.detail;
  throw new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`);
}

newChat.addEventListener('click', async () => {
  newChat.disabled = true;
  try {
    const response = await check(await fetch('/conversations', {method: 'POST', credentials: 'same-origin'}));
    conversationId = (await response.json()).conversation_id;
    messages.replaceChildren();
    document.querySelector('#welcome').hidden = false;
    statusText.className = '';
    statusText.textContent = 'New conversation created';
    input.focus();
  } catch (error) {
    statusText.textContent = error.message;
    statusText.className = 'error';
  } finally { newChat.disabled = false; }
});

document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
  input.value = button.dataset.question;
  input.focus();
}));
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!controller) form.requestSubmit();
  }
});
stop.addEventListener('click', () => controller?.abort());
form.addEventListener('submit', async event => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || controller) return;
  message('user', question);
  const reply = message('assistant', '');
  reply.card.classList.add('pending');
  reply.note.textContent = 'Generating · Content pending validation';
  input.value = '';
  controller = new AbortController();
  send.disabled = newChat.disabled = true;
  stop.hidden = false;
  statusText.className = '';
  statusText.textContent = 'Retrieving and generating…';
  let completed = false;
  let reader;
  try {
    const response = await check(await fetch(form.dataset.endpoint, {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question, conversation_id: conversationId})
    }));
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    function consume(frame) {
      const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!data || data === '[DONE]') return;
      const item = JSON.parse(data);
      if (item.conversation_id) conversationId = item.conversation_id;
      if (item.type === 'error') throw new Error(`${item.detail} (${item.request_id})`);
      if (item.token) reply.body.textContent += item.token;
      if (item.sources) sources(reply.card, item.sources);
      if (item.type === 'complete' && item.validated === true) {
        completed = true;
        reply.body.textContent = item.answer;
        reply.note.textContent = `Citation numbers checked · ${(item.latency_ms / 1000).toFixed(2)} seconds · Verify that the sources support the answer`;
        reply.card.classList.remove('pending');
        statusText.textContent = 'Complete';
      }
    }
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        consume(frame);
      }
      if (done) break;
    }
    if (!completed) throw new Error('The connection ended before the answer completed or passed validation');
  } catch (error) {
    reply.card.classList.add('error');
    reply.card.classList.remove('pending');
    reply.note.textContent = error.name === 'AbortError' ? 'Stopped · This response did not complete validation' : error.message;
    statusText.textContent = reply.note.textContent;
    statusText.className = 'error';
  } finally {
    await reader?.cancel().catch(() => {});
    controller = null;
    send.disabled = newChat.disabled = false;
    stop.hidden = true;
    input.focus();
  }
});
