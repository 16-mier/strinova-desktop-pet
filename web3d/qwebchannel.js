// qwebchannel.js —— Qt WebChannel 的 JavaScript 客户端（自实现，兼容 PyQt6/Qt6 实际协议）
//
// 官方实现编译在 Qt6WebChannel.dll 内部，无法直接取文件，故此处实现等价版本。
// 协议要点（实测 Qt 6.11 实际下发的 init 报文）：
//   "methods":  { "<index>": "<name>(<signature>)" }  ← 名字带参数签名，必须剥离
//   "signals":  { "<index>": "<name>(<signature>)" }
// 若不做签名剥离，JS 侧只能拿到 "ping(QString)" 这种键，调用 py.ping() 会报
// "not a function"。本实现同时兼容数组 / 索引对象 / 名字映射三种形态。
(function () {
  "use strict";
  if (window.QWebChannel) return;

  var T = {
    signal: 1, propertyUpdate: 2, init: 3, idle: 4, debug: 5,
    invokeMethod: 6, connectToSignal: 7, disconnectFromSignal: 8,
    setProperty: 9, response: 10,
  };

  // 剥离参数签名："ping(QString)" -> "ping"
  function bareName(s) {
    var i = String(s).indexOf("(");
    return i >= 0 ? String(s).slice(0, i) : String(s);
  }

  // 把 Qt 下发的 methods/signals 统一成 [名字, 索引] 列表。
  //
  // ★ 实测 Qt 6.11 (PyQt6) 的真实格式是【数组】：每项形如 [名字, 索引]，
  //   且同名条目会重复出现（"ping" 与 "ping(QString)" 各一条）。
  //   早期实现按对象解析，导致方法一个都没绑上 → JS 报 "py.ping is not a function"。
  //   这里同时兼容数组 / 对象 / 纯字符串三种形态，并去重（保留无签名版本）。
  function entries(obj) {
    var out = [];
    if (!obj) return out;
    if (Array.isArray(obj)) {
      obj.forEach(function (v, i) {
        if (Array.isArray(v)) {
          // ["ping", 4] 或 ["ping(QString)", 4]
          out.push([bareName(v[0]), v[1] != null ? v[1] : i]);
        } else if (typeof v === "string") {
          out.push([bareName(v), i]);
        } else if (v && typeof v === "object") {
          out.push([bareName(v.name || v[0] || ""), v.index != null ? v.index : i]);
        }
      });
      return dedupe(out);
    }
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (typeof v === "string") out.push([bareName(v), isNaN(+k) ? k : +k]);
      else if (typeof v === "number") out.push([bareName(k), v]);
    });
    return dedupe(out);
  }

  // 去重：同名保留第一个（顺序上无签名版本在前）
  function dedupe(list) {
    var seen = {}, out = [];
    list.forEach(function (e) {
      var n = e[0];
      if (!n || seen[n]) return;
      seen[n] = 1;
      out.push(e);
    });
    return out;
  }

  function QWebChannel(transport, initCallback) {
    if (!transport || typeof transport.send !== "function") {
      console.error("[QWebChannel] transport 无效");
      return;
    }
    var channel = this;
    this.transport = transport;
    this.execCallbacks = {};
    this.execId = 0;
    this.objects = {};

    this.send = function (data) {
      channel.transport.send(typeof data === "string" ? data : JSON.stringify(data));
    };

    this.exec = function (data, callback) {
      if (!callback) { channel.send(data); return; }
      if (channel.execId === Number.MAX_VALUE) channel.execId = Number.MIN_VALUE;
      data.id = channel.execId++;
      channel.execCallbacks[data.id] = callback;
      channel.send(data);
    };

    this.transport.onmessage = function (message) {
      var data = message.data;
      if (typeof data === "string") { try { data = JSON.parse(data); } catch (e) { return; } }
      switch (data.type) {
        case T.signal: channel.handleSignal(data); break;
        case T.response: channel.handleResponse(data); break;
        case T.propertyUpdate: channel.handlePropertyUpdate(data); break;
        default: break;
      }
    };

    this.handleSignal = function (message) {
      var object = channel.objects[message.object];
      if (object) object.signalEmitted(message.signal, message.args);
    };

    this.handleResponse = function (message) {
      if (!message.hasOwnProperty("id")) return;
      var cb = channel.execCallbacks[message.id];
      if (cb) cb(message.data);
      delete channel.execCallbacks[message.id];
    };

    this.handlePropertyUpdate = function (message) {
      var list = message.data || [];
      for (var i = 0; i < list.length; i++) {
        var d = list[i];
        var object = channel.objects[d.object];
        if (object) object.propertyUpdate(d.signals, d.properties);
      }
      channel.exec({ type: T.idle });
    };

    this.debug = function (message) {
      channel.send({ type: T.debug, data: message });
    };

    channel.exec({ type: T.init }, function (data) {
      Object.keys(data || {}).forEach(function (name) {
        new QObject(name, data[name], channel);
      });
      Object.keys(channel.objects).forEach(function (n) {
        channel.objects[n].unwrapProperties();
      });
      if (initCallback) initCallback(channel);
      channel.exec({ type: T.idle });
    });
  }

  function QObject(name, data, webChannel) {
    this.__id__ = name;
    webChannel.objects[name] = this;
    this.__objectSignals__ = {};
    this.__propertyCache__ = {};
    var object = this;

    this.unwrapProperties = function () {
      Object.keys(object.__propertyCache__).forEach(function (k) {
        object.__propertyCache__[k] = object.__propertyCache__[k];
      });
    };

    this.propertyUpdate = function (signals, properties) {
      Object.keys(properties || {}).forEach(function (p) {
        if (object.__propertyCache__.hasOwnProperty(p)) object.__propertyCache__[p] = properties[p];
      });
      Object.keys(signals || {}).forEach(function (sig) {
        var idx = object.__sigIndex__ ? object.__sigIndex__[sig] : undefined;
        var list = object.__objectSignals__[sig] || object.__objectSignals__[idx];
        if (list) list.slice().forEach(function (e) {
          try { e[0].apply(e[1] || null, signals[sig]); } catch (err) { console.error(err); }
        });
      });
    };

    this.signalEmitted = function (signal, args) {
      var list = object.__objectSignals__[signal];
      if (list) list.slice().forEach(function (e) {
        try { e[0].apply(e[1] || null, args); } catch (err) { console.error(err); }
      });
    };

    this.methodCall = function (method, args) {
      var a = Array.prototype.slice.call(args);
      return new Promise(function (resolve) {
        webChannel.exec(
          { type: T.invokeMethod, object: object.__id__, method: method, args: a },
          function (response) { resolve(response); }
        );
      });
    };

    // ---- 方法绑定（关键修复：剥离 "(QString)" 之类的签名）----
    entries(data.methods).forEach(function (e) {
      var mName = e[0];
      if (!mName) return;
      object[mName] = function () { return object.methodCall(mName, arguments); };
    });

    // ---- 属性绑定（实测格式：[[0, "objectName", [1,2], ""], ...]）----
    var props = data.properties || [];
    if (props && !Array.isArray(props)) props = Object.keys(props).map(function (k) {
      return [props[k], k, [], ""];
    });
    props.forEach(function (p) {
      if (!Array.isArray(p) || p.length < 2) return;
      var idx = p[0], pName = p[1], typeInfo = p[2] || [], initVal = p[3];
      if (!pName) return;
      object.__propertyCache__[pName] = initVal;
      Object.defineProperty(object, pName, {
        configurable: true, enumerable: true,
        get: function () { return object.__propertyCache__[pName]; },
        set: function (v) {
          object.__propertyCache__[pName] = v;
          webChannel.exec({ type: T.setProperty, object: object.__id__, property: pName, value: v });
        },
      });
    });

    // ---- 信号绑定（connect / disconnect）----
    object.__sigIndex__ = {};
    entries(data.signals).forEach(function (e) {
      var sName = e[0], sIdx = e[1];
      if (!sName) return;
      object.__sigIndex__[sName] = sIdx;
      if (Object.prototype.hasOwnProperty.call(object, sName)) return;  // 不覆盖同名方法
      object[sName] = {
        connect: function (func, context) {
          var key = object.__objectSignals__[sIdx] ? sIdx : sName;
          object.__objectSignals__[key] = object.__objectSignals__[key] || [];
          object.__objectSignals__[key].push([func, context]);
          webChannel.exec({ type: T.connectToSignal, object: object.__id__, signal: sIdx });
        },
        disconnect: function (func) {
          [sIdx, sName].forEach(function (key) {
            var list = object.__objectSignals__[key] || [];
            for (var i = list.length - 1; i >= 0; i--) {
              if (list[i][0] === func) list.splice(i, 1);
            }
          });
          webChannel.exec({ type: T.disconnectFromSignal, object: object.__id__, signal: sIdx });
        },
      };
    });
  }

  window.QWebChannel = QWebChannel;
})();
