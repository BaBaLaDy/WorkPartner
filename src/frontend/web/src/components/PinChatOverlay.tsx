import { useCallback, useEffect, useRef, useState } from 'react';
import { api, sendChatMessage } from '../api';
import { useStore, type Pin, type SessionMessage } from '../store';
import { pick } from '../locale';
import { Msg } from './SessionMsg';

interface PinChatOverlayProps {
  pin: Pin;
  onClose: () => void;
}

export function PinChatOverlay({ pin, onClose }: PinChatOverlayProps) {
  const locale = useStore((s) => s.locale);
  const setActiveTab = useStore((s) => s.setActiveTab);
  const setActiveThreadId = useStore((s) => s.setActiveThreadId);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [input, setInput] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [sending, setSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load session messages on open
  useEffect(() => {
    if (!pin.task_id) return;
    api.getTaskSession(pin.task_id)
      .then((data) => {
        if (data.messages) {
          setMessages(data.messages.slice(-20));
        }
      })
      .catch(() => {});
  }, [pin.task_id]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingText, scrollToBottom]);

  // Handle backdrop click to close
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  const handleSend = async () => {
    if (!input.trim() || sending) return;
    setSending(true);
    setStreamingText('');

    const userMsg: SessionMessage = { role: 'user', content: input };
    setMessages((prev) => [...prev, userMsg]);
    const text = input;
    setInput('');

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await sendChatMessage(
        text,
        (fullText) => setStreamingText(fullText),
        () => {
          setStreamingText('');
          setSending(false);
          // Refresh messages after completion
          api.getTaskSession(pin.task_id)
            .then((data) => {
              if (data.messages) setMessages(data.messages.slice(-20));
            })
            .catch(() => {});
        },
        pin.thread_id,
        controller.signal,
      );
    } catch {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNavigateTimeline = () => {
    onClose();
    setActiveThreadId(pin.thread_id);
    setActiveTab('chat');
  };

  return (
    <div className="pin-chat-overlay" onClick={handleBackdropClick}>
      <div className="pin-chat-overlay__panel">
        <div className="pin-chat-overlay__header">
          <h3 className="pin-chat-overlay__title">{pin.title}</h3>
          <button className="pin-chat-overlay__close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="pin-chat-overlay__summary">
          <div className="pin-chat-overlay__summary-label">
            {pick(locale, '摘要', 'Summary')}
          </div>
          {pin.summary}
        </div>

        <div className="pin-chat-overlay__messages">
          {messages.map((msg, i) => (
            <Msg key={i} msg={msg} />
          ))}
          {streamingText && (
            <div className="msg msg-assistant">
              <div className="msg-bubble msg-bubble-assistant">
                <p>{streamingText}<span className="cursor-blink" /></p>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="pin-chat-overlay__composer">
          <textarea
            className="pin-chat-overlay__input"
            placeholder={pick(locale, '继续追问...', 'Ask a follow-up...')}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className="pin-chat-overlay__send"
            onClick={handleSend}
            disabled={sending || !input.trim()}
          >
            {sending ? pick(locale, '发送中...', 'Sending...') : pick(locale, '发送', 'Send')}
          </button>
        </div>

        <div className="pin-chat-overlay__link">
          <a href="#" onClick={(e) => { e.preventDefault(); handleNavigateTimeline(); }}>
            {pick(locale, '查看完整 session →', 'View full session →')}
          </a>
        </div>
      </div>
    </div>
  );
}
