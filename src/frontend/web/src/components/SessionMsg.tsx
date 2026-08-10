import { type SessionMessage } from '../store';

export function Msg({ msg }: { msg: SessionMessage }) {
  if (!msg || !msg.role) return null;

  switch (msg.role) {
    case 'user':
      return (
        <div className="msg msg-user">
          <div className="msg-bubble msg-bubble-user">
            <p>{String(msg.content ?? '')}</p>
          </div>
        </div>
      );
    case 'assistant':
      return (
        <div className="msg msg-assistant">
          <div className="msg-bubble msg-bubble-assistant">
            <p>{String(msg.content ?? '')}</p>
          </div>
        </div>
      );
    case 'tool_call':
      return (
        <div className="msg msg-tool">
          <div className="msg-bubble msg-bubble-tool">
            <span className="tool-name">{msg.name || 'unknown'}()</span>
            {msg.args && typeof msg.args === 'object' && Object.keys(msg.args).length > 0 && (
              <pre className="tool-args">{JSON.stringify(msg.args, null, 2)}</pre>
            )}
          </div>
        </div>
      );
    case 'tool_result':
      return (
        <div className="msg msg-tool-result">
          <div className="msg-bubble msg-bubble-tool-result">
            <pre className="tool-result-content">{String(msg.content ?? '')}</pre>
          </div>
        </div>
      );
    default:
      return null;
  }
}
