export function useTaskLog() {
  function subscribe(_taskId: string) {}
  function disconnect() {}
  return { subscribe, disconnect };
}
