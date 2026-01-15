(function () {
  const ws = new WebSocket(`ws://${location.host}/__hmr`);
  let connected = false;
  ws.onopen = () => (connected = true);
  ws.onmessage = () => location.reload();
  ws.onclose = () => connected && setTimeout(() => location.reload(), 1000);
})();
