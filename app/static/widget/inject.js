/**
 * RAG Chatbot Widget Injector
 *
 * 사용법:
 * <script
 *   src="https://your-domain.com/widget/inject.js"
 *   data-widget-key="wk_xxx"
 *   data-api-base="https://api.snapagent.shop"
 * ></script>
 */
(function() {
  'use strict';

  if (window.RAGChatbotWidget) {
    console.warn('[RAG Widget] Already loaded');
    return;
  }

  window.RAGChatbotWidget = {
    config: null,
    widgetKey: null,
    apiBaseUrl: null,
    frontendUrl: null,
    session: null,
    isOpen: false,
    bubbleButton: null,
    chatContainer: null,
    chatIframe: null,

    init: async function(widgetKey, apiBaseUrl, frontendUrl) {
      try {
        console.log('[RAG Widget] Initializing with key:', widgetKey);
        console.log('[RAG Widget] API Base URL:', apiBaseUrl);
        console.log('[RAG Widget] Frontend URL:', frontendUrl);

        this.widgetKey = widgetKey;
        this.apiBaseUrl = apiBaseUrl;
        this.frontendUrl = frontendUrl || this.getFrontendUrl();

        this.config = await this.loadConfig(widgetKey);

        this.createBubbleButton();

        this.attachEvents();

        if (this.config.config.auto_open) {
          const delay = this.config.config.auto_open_delay || 5000;
          setTimeout(() => this.openChat(), delay);
        }

        this.trackEvent('load');

        console.log('[RAG Widget] Initialized successfully');
      } catch (error) {
        console.error('[RAG Widget] Init failed:', error);
        this.showError('위젯을 로드할 수 없습니다. 나중에 다시 시도해주세요.');
      }
    },

    loadConfig: async function(widgetKey) {
      const url = `${this.apiBaseUrl}/api/v1/widget/config/${widgetKey}`;

      const res = await fetch(url, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || 'Failed to load config');
      }

      return await res.json();
    },

    openChat: async function() {
      if (this.isOpen) return;

      try {
        await this.createSession();

        this.createChatIframe();
        this.isOpen = true;

        if (this.bubbleButton) {
          this.bubbleButton.style.display = 'none';
        }

        this.trackEvent('open');
      } catch (error) {
        console.error('[RAG Widget] Failed to open chat:', error);
        this.showError('채팅을 시작할 수 없습니다. 나중에 다시 시도해주세요.');
      }
    },

    createSession: async function() {
      if (this.session) {
        console.log('[RAG Widget] Session already exists');
        return;
      }

      const url = `${this.apiBaseUrl}/api/v1/widget/sessions`;

      const payload = {
        widget_key: this.widgetKey,
        widget_signature: {
          signature: this.config.signature,
          expires_at: this.config.expires_at,
          nonce: this.config.nonce,
          widget_key: this.widgetKey,
        },
        fingerprint: this.getFingerprint(),
        context: this.getContext(),
        user_info: null,
      };

      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Session creation failed' }));
        throw new Error(error.detail || 'Failed to create session');
      }

      const session = await res.json();

      this.session = {
        session_id: session.session_id,
        session_token: session.session_token,
        refresh_token: session.refresh_token,
        expires_at: session.expires_at,
      };

      console.log('[RAG Widget] Session created successfully');
    },

    closeChat: function() {
      if (!this.isOpen) return;

      if (this.chatContainer) {
        this.chatContainer.style.display = 'none';
      }

      if (this.bubbleButton) {
        this.bubbleButton.style.display = 'flex';
      }

      this.isOpen = false;

      this.trackEvent('close');
    },

    toggleChat: function() {
      if (this.isOpen) {
        this.closeChat();
      } else {
        this.openChat();
      }
    },

    createBubbleButton: function() {
      const button = document.createElement('div');
      button.id = 'rag-chatbot-bubble';
      button.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="white">
          <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
        </svg>
      `;

      const position = this.config.config.position || 'bottom-right';
      const color = this.config.config.primary_color || '#0066FF';

      button.style.cssText = `
        position: fixed;
        ${this.getPositionStyle(position)};
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: ${color};
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 999999;
        transition: transform 0.2s;
      `;

      button.onmouseover = () => {
        button.style.transform = 'scale(1.1)';
      };

      button.onmouseout = () => {
        button.style.transform = 'scale(1)';
      };

      button.onclick = () => this.toggleChat();

      document.body.appendChild(button);
      this.bubbleButton = button;
    },

    createChatIframe: function() {
      if (this.chatContainer) {
        this.chatContainer.style.display = 'block';
        this.sendSessionToIframe();
        return;
      }

      const container = document.createElement('div');
      container.id = 'rag-chatbot-container';

      const position = this.config.config.position || 'bottom-right';
      container.style.cssText = `
        position: fixed;
        ${this.getPositionStyle(position, true)};
        width: 400px;
        height: 600px;
        max-width: calc(100vw - 40px);
        max-height: calc(100vh - 120px);
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.2);
        z-index: 999998;
        background: white;
        overflow: hidden;
      `;

      const closeBtn = document.createElement('div');
      closeBtn.innerHTML = '×';
      closeBtn.style.cssText = `
        position: absolute;
        top: 8px;
        right: 8px;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: rgba(0,0,0,0.1);
        color: #333;
        font-size: 24px;
        line-height: 32px;
        text-align: center;
        cursor: pointer;
        z-index: 1;
        transition: background 0.2s;
      `;
      closeBtn.onmouseover = () => {
        closeBtn.style.background = 'rgba(0,0,0,0.2)';
      };
      closeBtn.onmouseout = () => {
        closeBtn.style.background = 'rgba(0,0,0,0.1)';
      };
      closeBtn.onclick = () => this.closeChat();

      const iframe = document.createElement('iframe');
      iframe.src = `${this.frontendUrl}/widget/chat/${this.widgetKey}`;
      iframe.style.cssText = 'width: 100%; height: 100%; border: none;';
      iframe.allow = 'clipboard-write';

      iframe.onload = () => {
        // React 컴포넌트 마운트 대기를 위한 지연된 재시도
        setTimeout(() => this.sendSessionToIframe(), 100);
        setTimeout(() => this.sendSessionToIframe(), 300);
        setTimeout(() => this.sendSessionToIframe(), 500);
      };

      container.appendChild(closeBtn);
      container.appendChild(iframe);
      document.body.appendChild(container);

      this.chatContainer = container;
      this.chatIframe = iframe;
    },

    sendSessionToIframe: function() {
      if (!this.chatIframe || !this.session) {
        console.warn('[RAG Widget] Cannot send session: iframe or session not ready');
        return;
      }

      console.log('[RAG Widget] Sending postMessage to iframe:', {
        targetOrigin: this.frontendUrl,
        currentWindowOrigin: window.location.origin,
        iframeUrl: this.chatIframe.src
      });

      this.chatIframe.contentWindow.postMessage({
        type: 'WIDGET_SESSION',
        session: {
          session_id: this.session.session_id,
          session_token: this.session.session_token,
          refresh_token: this.session.refresh_token,
          expires_at: this.session.expires_at,
        },
        config: this.config,
        apiBaseUrl: this.apiBaseUrl,
      }, this.frontendUrl);

      console.log('[RAG Widget] Session sent to iframe via postMessage');
    },

    getPositionStyle: function(position, isContainer = false) {
      const offset = isContainer ? '80px' : '20px';
      const positions = {
        'bottom-right': `bottom: ${offset}; right: 20px;`,
        'bottom-left': `bottom: ${offset}; left: 20px;`,
        'top-right': `top: ${offset}; right: 20px;`,
        'top-left': `top: ${offset}; left: 20px;`,
      };
      return positions[position] || positions['bottom-right'];
    },

    getFingerprint: function() {
      return {
        user_agent: navigator.userAgent,
        screen_resolution: `${screen.width}x${screen.height}`,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        language: navigator.language,
        platform: navigator.platform,
      };
    },

    getContext: function() {
      return {
        page_url: window.location.href,
        page_title: document.title,
        referrer: document.referrer || null,
        utm_source: this.getURLParam('utm_source'),
        utm_medium: this.getURLParam('utm_medium'),
      };
    },

    getURLParam: function(name) {
      const params = new URLSearchParams(window.location.search);
      return params.get(name);
    },

    getFrontendUrl: function() {
      const scripts = document.getElementsByTagName('script');
      for (let script of scripts) {
        if (script.src && script.src.includes('/widget/inject.js')) {
          const url = new URL(script.src);
          return `${url.protocol}//${url.host}`;
        }
      }
      return window.location.origin;
    },

    trackEvent: function(event) {
      if (!this.config || !this.widgetKey) return;

      const url = `${this.apiBaseUrl}/api/v1/widget/config/${this.widgetKey}/track`;

      fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          event,
          metadata: {
            user_agent: navigator.userAgent,
            referrer: document.referrer,
          },
        }),
      }).catch(() => {
      });
    },

    showError: function(message) {
      alert(`[RAG Chatbot] ${message}`);
    },

    attachEvents: function() {
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.isOpen) {
          this.closeChat();
        }
      });
    },
  };

  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideIn {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    #rag-chatbot-container {
      animation: slideIn 0.3s ease-out;
    }
    @media (max-width: 768px) {
      #rag-chatbot-container {
        width: calc(100vw - 20px) !important;
        height: calc(100vh - 80px) !important;
        bottom: 10px !important;
        right: 10px !important;
        left: 10px !important;
      }
    }
  `;
  document.head.appendChild(style);

  const currentScript = document.currentScript;
  if (currentScript) {
    const widgetKey = currentScript.getAttribute('data-widget-key');
    const apiBaseUrl = currentScript.getAttribute('data-api-base');
    const frontendUrl = currentScript.getAttribute('data-frontend-url');

    if (!widgetKey) {
      console.error('[RAG Widget] Missing data-widget-key attribute');
      return;
    }

    if (!apiBaseUrl) {
      console.error('[RAG Widget] Missing data-api-base attribute');
      console.error('[RAG Widget] Usage: <script src="..." data-widget-key="wk_xxx" data-api-base="https://api.snapagent.shop" data-frontend-url="https://snapagent.shop">');
      return;
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        window.RAGChatbotWidget.init(widgetKey, apiBaseUrl, frontendUrl);
      });
    } else {
      window.RAGChatbotWidget.init(widgetKey, apiBaseUrl, frontendUrl);
    }
  }
})();
