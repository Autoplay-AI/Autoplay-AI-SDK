/**
 * SSE client example — JavaScript (browser + Node.js)
 *
 * Browser:
 *   Copy the ConnectorClient class into your frontend code.
 *   Note: browsers cannot set custom headers on EventSource.
 *   If your connector requires auth, proxy the SSE endpoint through
 *   your own backend (recommended) or disable auth for browser-only setups.
 *
 * Node.js:
 *   npm install eventsource
 *   CONNECTOR_URL=https://<host>/stream/acme_prod CONNECTOR_TOKEN=tok_xyz node client_example.js
 */

// ---------------------------------------------------------------------------
// ConnectorClient
// ---------------------------------------------------------------------------

class ConnectorClient {
  /**
   * @param {string} url   Full URL to GET /stream/{product_id}
   * @param {string} token Bearer token (leave empty if no auth required)
   */
  constructor(url, token = "") {
    this._url = url;
    this._token = token;
    this._es = null;
    this._backoff = 1000; // ms
    this._maxBackoff = 30000; // ms
    this._stopped = false;

    this.onActions = null;  // (payload) => void
    this.onSummary = null;  // (payload) => void
  }

  /** Start listening. Reconnects automatically on failure. */
  connect() {
    if (this._stopped) return;
    this._openConnection();
  }

  /** Stop listening and close the connection. */
  disconnect() {
    this._stopped = true;
    if (this._es) {
      this._es.close();
      this._es = null;
    }
  }

  _openConnection() {
    // Browser EventSource does not support custom headers.
    // In Node.js, the 'eventsource' package accepts headers via the second arg.
    const options = this._token
      ? { headers: { Authorization: `Bearer ${this._token}` } }
      : {};

    // In a browser, replace `require('eventsource')` with the global `EventSource`.
    const EventSource =
      typeof globalThis.EventSource !== "undefined"
        ? globalThis.EventSource
        : require("eventsource");

    const es = new EventSource(this._url, options);
    this._es = es;

    es.onopen = () => {
      console.log("[connector] connected");
      this._backoff = 1000; // reset on successful connection
    };

    es.onmessage = (event) => {
      this._handleMessage(event.data);
    };

    // Named 'heartbeat' events — ignore
    es.addEventListener("heartbeat", () => {});

    es.onerror = (err) => {
      es.close();
      this._es = null;
      if (this._stopped) return;

      console.warn(`[connector] connection error — retrying in ${this._backoff}ms`, err);
      setTimeout(() => this._openConnection(), this._backoff);
      this._backoff = Math.min(this._backoff * 2, this._maxBackoff);
    };
  }

  _handleMessage(data) {
    let payload;
    try {
      payload = JSON.parse(data);
    } catch (e) {
      console.warn("[connector] could not parse event data:", data.slice(0, 200));
      return;
    }

    if (payload.type === "actions" && typeof this.onActions === "function") {
      this.onActions(payload);
    } else if (payload.type === "summary" && typeof this.onSummary === "function") {
      this.onSummary(payload);
    }
  }
}

// ---------------------------------------------------------------------------
// Usage example (Node.js)
// ---------------------------------------------------------------------------

if (typeof require !== "undefined" && require.main === module) {
  const url =
    process.env.CONNECTOR_URL || "http://localhost:8080/stream/acme_prod";
  const token = process.env.CONNECTOR_TOKEN || "";

  const client = new ConnectorClient(url, token);

  client.onActions = (payload) => {
    console.log(
      `[actions] product=${payload.product_id} session=${payload.session_id} count=${payload.count}`
    );
    for (const action of payload.actions) {
      console.log(`  [${action.canonical_url}] ${action.title}`);
    }
  };

  client.onSummary = (payload) => {
    console.log(
      `[summary] product=${payload.product_id} session=${payload.session_id} replaces=${payload.replaces}`
    );
    console.log(`  ${payload.summary}`);
  };

  client.connect();
  console.log(`[connector] listening on ${url}`);
}

// ---------------------------------------------------------------------------
// Browser usage (copy the ConnectorClient class above, then):
// ---------------------------------------------------------------------------
//
// const client = new ConnectorClient("https://your-connector/stream/acme_prod");
// // Note: auth header not supported in browser EventSource — proxy if needed.
//
// client.onActions = (payload) => {
//   console.log("User actions:", payload.actions);
// };
//
// client.onSummary = (payload) => {
//   console.log("Session summary:", payload.summary);
// };
//
// client.connect();
