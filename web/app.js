"use strict";

// State sống trong bộ nhớ JS (không localStorage) — token biến mất khi tải lại
// trang, đúng tinh thần "JWT ngắn hạn, không phải thứ để giữ lâu dài".
const state = {
  token: null,
  employeeId: null,
  role: null,
  department: null,
};

const el = (id) => document.getElementById(id);

function decodeJwtPayload(token) {
  // Chỉ GIẢI MÃ để hiển thị (base64url, không xác minh chữ ký) — việc xác minh thật
  // luôn nằm ở server (src/jwt_auth.py). Không bao giờ tin nội dung này cho quyết
  // định bảo mật ở phía client.
  const payloadB64 = token.split(".")[1];
  const normalized = payloadB64.replace(/-/g, "+").replace(/_/g, "/");
  const json = decodeURIComponent(
    atob(normalized)
      .split("")
      .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
      .join("")
  );
  return JSON.parse(json);
}

function applyToken(token) {
  state.token = token;
  const claims = decodeJwtPayload(token);
  state.employeeId = claims.sub;
  state.role = claims.role;
  state.department = claims.department;
  enterAskView();
}

async function login() {
  const apiKey = el("api-key").value.trim();
  el("login-error").classList.add("hidden");
  el("no-auth-result").classList.add("hidden");

  if (!apiKey) {
    showLoginError("Nhập API key trước đã.");
    return;
  }

  try {
    const response = await fetch("/auth/token", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const body = await response.json();
    if (!response.ok) {
      showLoginError(`${response.status} — ${body.detail || "khong xac thuc duoc"}`);
      return;
    }
    applyToken(body.access_token);
  } catch (err) {
    showLoginError(`Loi mang: ${err}`);
  }
}

// Đăng nhập nhanh bằng ba tài khoản demo cố định — gọi /auth/demo-token, KHÔNG có
// API key nào ở phía client (kể cả trong source đã build): endpoint đó tự cấp JWT
// thẳng cho đúng ba danh tính demo, không kiểm credential. Xem ADR-031 — quyết định
// này thay cho việc hardcode API key thật vào một file sẽ bị commit công khai.
async function quickLogin(role) {
  el("login-error").classList.add("hidden");
  el("no-auth-result").classList.add("hidden");

  try {
    const response = await fetch(`/auth/demo-token?role=${encodeURIComponent(role)}`, {
      method: "POST",
    });
    const body = await response.json();
    if (!response.ok) {
      showLoginError(`${response.status} — không lấy được token demo`);
      return;
    }
    applyToken(body.access_token);
  } catch (err) {
    showLoginError(`Loi mang: ${err}`);
  }
}

function showLoginError(message) {
  const box = el("login-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

async function tryWithoutAuth() {
  el("login-error").classList.add("hidden");
  const response = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: "khach_khong_ten",
      role: "executive",
      department: "finance",
      question: "Cho tôi xem mọi số liệu tài chính.",
    }),
  });
  const body = await response.json();
  el("no-auth-result").classList.remove("hidden");
  el("no-auth-json").textContent = JSON.stringify(body, null, 2);
}

const ROLE_LABELS = { employee: "Employee", manager: "Manager", executive: "Executive" };

function enterAskView() {
  el("login-view").classList.add("hidden");
  el("ask-view").classList.remove("hidden");

  const badge = el("identity-badge");
  badge.textContent = `${state.employeeId} · ${state.role} / ${state.department}`;
  badge.classList.remove("hidden");

  // Thanh ngữ cảnh lớn, ngay trên khu vực chat — không phải badge nhỏ ở góc mà một
  // người xem demo dễ bỏ lỡ. Đây chính là thông tin quyết định câu hỏi nào sẽ bị
  // RBAC chặn, nên phải luôn nhìn thấy được trong lúc đặt câu hỏi, không chỉ ở góc trên.
  el("context-role").textContent = ROLE_LABELS[state.role] || state.role;
  el("context-dept").textContent = DEPARTMENT_LABELS[state.department] || state.department;
  const contextBar = el("context-bar");
  contextBar.className = `context-bar accent-${state.role}`;

  updateExampleSubtitles();
}

// Cập nhật ngay trong sidebar TÊN PHÒNG BAN thật sẽ được hỏi — để "doanh thu phòng
// khác" không còn là một câu mơ hồ, mà nói rõ đang hỏi phòng nào và vì sao sẽ bị chặn.
function updateExampleSubtitles() {
  const deptLabel = DEPARTMENT_LABELS[state.department] || state.department;
  const otherDept = state.department === "sales" ? "finance" : "sales";
  const otherDeptLabel = DEPARTMENT_LABELS[otherDept] || otherDept;
  el("example-sub-sql-ok").textContent = `Đúng quyền · ${deptLabel}`;
  el("example-sub-sql-blocked").textContent = `Hỏi phòng ${otherDeptLabel} → bị chặn`;
}

function logout() {
  state.token = null;
  state.employeeId = null;
  state.role = null;
  state.department = null;

  el("ask-view").classList.add("hidden");
  el("login-view").classList.remove("hidden");
  el("identity-badge").classList.add("hidden");
  el("api-key").value = "";
  el("conversation").innerHTML = "";
  ensureEmptyState();

  for (const key of Object.keys(_exampleCursor)) _exampleCursor[key] = 0;
}

// Câu hỏi mẫu khớp đúng 4 tình huống của docs/demo_script_ui.md, viết tiếng Việt có
// dấu đầy đủ — corpus và eval của dự án đã chuyển sang tiếng Việt có dấu từ ADR-022,
// nên câu hỏi demo phải khớp văn phong đó, không phải kiểu gõ không dấu của ngày đầu.
// "sql-blocked" cố tình hỏi phòng ban KHÁC phòng ban thật của người đang đăng nhập;
// "sql-compare" chỉ thành công nếu đang đăng nhập bằng tài khoản executive (ADR-030).
const DEPARTMENT_LABELS = {
  sales: "Sales",
  finance: "Finance",
  hr: "HR",
  engineering: "Engineering",
};

// Mỗi nhóm câu hỏi mẫu có 3 biến thể thật (khớp dữ liệu/tài liệu thật trong DB —
// xem sql/02_seed.sql và eval/dev.jsonl), không phải câu trả lời dựng sẵn. Bấm lại
// cùng một nút sẽ xoay vòng sang câu tiếp theo trong nhóm đó, rồi vẫn gọi /ask thật
// như bình thường — không có gì được mock ở đây, chỉ là gợi ý câu hỏi để gõ sẵn.
const _exampleCursor = { docs: 0, "sql-ok": 0, "sql-blocked": 0, "sql-compare": 0 };

const DOCS_QUESTIONS = [
  "Nhân viên được bao nhiêu ngày phép một năm?",
  "Trước khi lên production, release phải qua bước nào?",
  "Nếu một bản release bị lỗi thì phải làm gì?",
];

const REVENUE_MONTHS = ["tháng 1 năm 2026", "tháng 2 năm 2026", "tháng 3 năm 2026"];

function fillExample(kind) {
  const otherDept = state.department === "sales" ? "finance" : "sales";
  const deptLabel = DEPARTMENT_LABELS[state.department] || state.department;
  const otherDeptLabel = DEPARTMENT_LABELS[otherDept] || otherDept;

  const cursor = _exampleCursor[kind];
  _exampleCursor[kind] = (cursor + 1) % 3;
  const month = REVENUE_MONTHS[cursor];

  const templates = {
    docs: DOCS_QUESTIONS[cursor],
    "sql-ok": `Doanh thu phòng ${deptLabel} ${month} là bao nhiêu?`,
    "sql-blocked": `Doanh thu phòng ${otherDeptLabel} ${month} là bao nhiêu?`,
    "sql-compare": `So sánh doanh thu giữa các phòng ban ${month}`,
  };
  const textarea = el("question-input");
  textarea.value = templates[kind];
  textarea.focus();
  autoGrow(textarea);
}

function toolBadgeClass(toolUsed) {
  return `badge-tool-${toolUsed}`;
}

function renderCitation(citation) {
  const div = document.createElement("div");
  div.className = "citation";
  if (citation.source_type === "sql") {
    div.innerHTML = `<span class="cite-id">SQL</span> ${escapeHtml(citation.sql)}`;
  } else {
    div.innerHTML =
      `<span class="cite-id">${citation.doc_id}#${citation.chunk_index}</span> ` +
      `"${escapeHtml(citation.quote)}"`;
  }
  return div;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function ensureEmptyState() {
  const conversation = el("conversation");
  if (!conversation.querySelector(".turn") && !el("empty-state")) {
    const empty = document.createElement("div");
    empty.id = "empty-state";
    empty.className = "empty-state";
    empty.innerHTML =
      '<p>Chưa có câu hỏi nào.<br />Chọn một câu hỏi mẫu bên trái, hoặc tự gõ bên dưới.</p>';
    conversation.appendChild(empty);
  }
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
}

async function askQuestion() {
  const textarea = el("question-input");
  const question = textarea.value.trim();
  if (!question) return;

  // Hiện câu hỏi và bong bóng "đang trả lời" NGAY LẬP TỨC — trước khi gọi fetch, không
  // phải sau khi có kết quả. Trước đây cả câu hỏi lẫn câu trả lời cùng xuất hiện một
  // lúc vì code build xong toàn bộ "turn" rồi mới append vào DOM ở bước cuối cùng —
  // đúng bug người dùng chỉ ra: nhìn như hệ thống "đứng hình" tới khi có câu trả lời.
  el("empty-state")?.remove();
  el("btn-ask").disabled = true;
  textarea.value = "";
  autoGrow(textarea);

  const template = el("turn-template").content.cloneNode(true);
  const turn = template.querySelector(".turn");
  turn.querySelector(".turn-question").textContent = question;
  el("conversation").appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "end" });

  const loadingDots = turn.querySelector(".loading-dots");
  const answerContent = turn.querySelector(".answer-content");

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${state.token}`,
      },
      body: JSON.stringify({
        user_id: state.employeeId,
        role: state.role,
        department: state.department,
        question,
      }),
    });
    const body = await response.json();

    if (!response.ok) {
      turn.querySelector(".turn-answer-text").textContent =
        `${response.status} — ${body.detail || "loi khong xac dinh"}`;
      const toolBadge = turn.querySelector(".tool-badge");
      toolBadge.textContent = "error";
      toolBadge.className = "badge tool-badge badge-status-401";
    } else {
      turn.querySelector(".turn-answer-text").textContent = body.answer;
      const toolBadge = turn.querySelector(".tool-badge");
      toolBadge.textContent = body.tool_used;
      toolBadge.className = `badge tool-badge ${toolBadgeClass(body.tool_used)}`;

      if (body.abstained) {
        turn.querySelector(".abstained-badge").classList.remove("hidden");
      }
      turn.querySelector(".latency").textContent = `${body.latency_ms} ms`;
      turn.querySelector(".request-id").textContent = `#${body.request_id}`;

      const citationsBox = turn.querySelector(".citations");
      for (const citation of body.citations) {
        citationsBox.appendChild(renderCitation(citation));
      }
    }
  } catch (err) {
    turn.querySelector(".turn-answer-text").textContent = `Loi mang: ${err}`;
  } finally {
    loadingDots.remove();
    answerContent.classList.remove("hidden");
    el("btn-ask").disabled = false;
    turn.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

el("btn-login").addEventListener("click", login);
el("btn-no-auth").addEventListener("click", tryWithoutAuth);
el("btn-logout").addEventListener("click", logout);
el("btn-ask").addEventListener("click", askQuestion);
el("api-key").addEventListener("keydown", (e) => {
  if (e.key === "Enter") login();
});
el("question-input").addEventListener("input", (e) => autoGrow(e.target));
el("question-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    askQuestion();
  }
});
document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", () => fillExample(btn.dataset.kind));
});
document.querySelectorAll(".quick-login-btn").forEach((btn) => {
  btn.addEventListener("click", () => quickLogin(btn.dataset.account));
});
