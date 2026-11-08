"use strict";

const ESTADOS = { ABIERTA: "Abierta", EN_PROGRESO: "En progreso", RESUELTA: "Resuelta", CERRADA: "Cerrada" };
const SEVERIDADES = { BAJA: "Baja", MEDIA: "Media", ALTA: "Alta", CRITICA: "Crítica" };
const SIGUIENTES = {
  ABIERTA: ["EN_PROGRESO", "CERRADA"],
  EN_PROGRESO: ["RESUELTA", "ABIERTA"],
  RESUELTA: ["CERRADA", "ABIERTA"],
  CERRADA: ["ABIERTA"],
};

const $ = (sel) => document.querySelector(sel);
let actual = null;

function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fecha(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("es-PE", { dateStyle: "medium", timeStyle: "short" });
}

function badge(clase, texto) {
  return `<span class="badge ${clase}">${esc(texto)}</span>`;
}

function toast(mensaje) {
  const t = $("#toast");
  t.textContent = mensaje;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2800);
}

async function api(ruta, opciones = {}) {
  const res = await fetch(ruta, {
    headers: opciones.body ? { "Content-Type": "application/json" } : {},
    ...opciones,
  });
  if (res.status === 204) return null;
  let datos = null;
  try { datos = await res.json(); } catch { datos = null; }
  if (!res.ok) {
    let msg = "No se pudo completar la operación.";
    if (datos && typeof datos.detail === "string") msg = datos.detail;
    else if (datos && Array.isArray(datos.detail) && datos.detail.length) {
      const d = datos.detail[0];
      msg = `${(d.loc || []).slice(-1)[0] || "dato"}: ${d.msg}`;
    }
    throw new Error(msg);
  }
  return datos;
}

async function cargarEstado() {
  const el = $("#almacenamiento");
  try {
    const h = await api("/health");
    if (h.almacenamiento === "cosmos") {
      el.className = "badge ok";
      el.textContent = "Azure Cosmos DB conectado";
    } else {
      el.className = "badge warn";
      el.textContent = "Modo demo (memoria)";
    }
  } catch {
    el.className = "badge warn";
    el.textContent = "Sin conexión a la base de datos";
  }
}

async function cargarResumen() {
  const r = await api("/api/resumen");
  $("#k-total").textContent = r.total;
  $("#k-abiertas").textContent = r.por_estado.ABIERTA;
  $("#k-progreso").textContent = r.por_estado.EN_PROGRESO;
  $("#k-cerradas").textContent = r.por_estado.RESUELTA + r.por_estado.CERRADA;
  $("#k-criticas").textContent = r.criticas_pendientes;

  const proyectos = Object.keys(r.por_proyecto);
  const sel = $("#filtros select[name=proyecto]");
  const elegido = sel.value;
  sel.innerHTML = '<option value="">Proyectos</option>' +
    proyectos.map((p) => `<option value="${esc(p)}">${esc(p)} (${r.por_proyecto[p]})</option>`).join("");
  if (proyectos.includes(elegido)) sel.value = elegido;
  $("#lista-proyectos").innerHTML = proyectos.map((p) => `<option value="${esc(p)}">`).join("");
}

async function cargarLista() {
  const datos = new FormData($("#filtros"));
  const params = new URLSearchParams();
  for (const [k, v] of datos) if (String(v).trim()) params.set(k, String(v).trim());
  const items = await api(`/api/incidencias?${params}`);
  const ul = $("#lista");
  ul.innerHTML = items.map((i) => `
    <li tabindex="0" data-proyecto="${esc(i.proyecto)}" data-id="${esc(i.id)}">
      <div>
        <div class="t">${esc(i.titulo)}</div>
        <div class="m">${esc(i.proyecto)} · ${esc(i.reportado_por)} · ${fecha(i.creado_en)} · ${i.num_comentarios} comentario(s)</div>
        <div class="m">${i.etiquetas.map((e) => `<span class="tag">#${esc(e)}</span>`).join(" ")}</div>
      </div>
      <div class="badges">
        ${badge("s-" + i.severidad, SEVERIDADES[i.severidad])}
        ${badge("e-" + i.estado, ESTADOS[i.estado])}
      </div>
    </li>`).join("");
  $("#vacio").hidden = items.length > 0;
  $("#contador").textContent = `${items.length} resultado(s)`;
}

async function refrescar() {
  try {
    await Promise.all([cargarResumen(), cargarLista()]);
  } catch (e) {
    toast(e.message);
  }
}

function pintarDetalle(d) {
  actual = d;
  $("#d-proyecto").textContent = `Proyecto: ${d.proyecto}`;
  $("#d-titulo").textContent = d.titulo;
  $("#d-badges").innerHTML = badge("s-" + d.severidad, SEVERIDADES[d.severidad]) +
    badge("e-" + d.estado, ESTADOS[d.estado]) +
    d.etiquetas.map((e) => `<span class="tag">#${esc(e)}</span>`).join(" ");
  $("#d-descripcion").textContent = d.descripcion || "Sin descripción.";
  $("#d-meta").textContent = `Reportada por ${d.reportado_por} el ${fecha(d.creado_en)} · Última actualización: ${fecha(d.actualizado_en)}`;
  $("#d-estado").innerHTML = SIGUIENTES[d.estado]
    .map((e) => `<option value="${e}">${ESTADOS[e]}</option>`).join("");
  $("#d-comentarios").innerHTML = d.comentarios.length
    ? d.comentarios.map((c) => `<li><strong>${esc(c.autor)}</strong> <span class="muted">${fecha(c.fecha)}</span><br>${esc(c.texto)}</li>`).join("")
    : '<li class="muted">Aún no hay comentarios.</li>';
  $("#d-historial").innerHTML = d.historial.map((h) => `<li>${h.de ? `${esc(ESTADOS[h.de])} → ` : "Creada como "}<strong>${esc(ESTADOS[h.a])}</strong> por ${esc(h.autor)} <span class="muted">${fecha(h.fecha)}</span></li>`).join("");
  $("#d-json").textContent = JSON.stringify(d, null, 2);
  $("#error-detalle").hidden = true;
}

async function abrirDetalle(proyecto, id) {
  try {
    const d = await api(`/api/incidencias/${encodeURIComponent(proyecto)}/${encodeURIComponent(id)}`);
    pintarDetalle(d);
    $("#detalle").showModal();
  } catch (e) {
    toast(e.message);
  }
}

function errorDetalle(msg) {
  const p = $("#error-detalle");
  p.textContent = msg;
  p.hidden = false;
}

$("#lista").addEventListener("click", (ev) => {
  const li = ev.target.closest("li[data-id]");
  if (li) abrirDetalle(li.dataset.proyecto, li.dataset.id);
});
$("#lista").addEventListener("keydown", (ev) => {
  const li = ev.target.closest("li[data-id]");
  if (li && (ev.key === "Enter" || ev.key === " ")) {
    ev.preventDefault();
    abrirDetalle(li.dataset.proyecto, li.dataset.id);
  }
});

let espera = null;
$("#filtros").addEventListener("input", () => {
  clearTimeout(espera);
  espera = setTimeout(() => cargarLista().catch((e) => toast(e.message)), 300);
});
$("#filtros").addEventListener("submit", (ev) => ev.preventDefault());

$("#form-crear").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const err = $("#error-crear");
  err.hidden = true;
  if (!form.checkValidity()) {
    const invalido = form.querySelector(":invalid");
    err.textContent = invalido.name === "proyecto"
      ? "Proyecto: usa minúsculas, números y guiones (2 a 40 caracteres)."
      : `Revisa el campo «${invalido.closest("label").firstChild.textContent.trim()}».`;
    err.hidden = false;
    invalido.focus();
    return;
  }
  const f = new FormData(form);
  const cuerpo = {
    proyecto: f.get("proyecto").trim().toLowerCase(),
    titulo: f.get("titulo"),
    descripcion: f.get("descripcion"),
    severidad: f.get("severidad"),
    reportado_por: f.get("reportado_por"),
    etiquetas: String(f.get("etiquetas") || "").split(",").map((e) => e.trim()).filter(Boolean),
  };
  const boton = form.querySelector("button");
  boton.disabled = true;
  try {
    await api("/api/incidencias", { method: "POST", body: JSON.stringify(cuerpo) });
    const autor = cuerpo.reportado_por;
    form.reset();
    form.reportado_por.value = autor;
    toast("Incidencia registrada");
    await refrescar();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    boton.disabled = false;
  }
});

$("#d-btn-estado").addEventListener("click", async () => {
  const autor = $("#d-autor-estado").value.trim();
  if (autor.length < 2) return errorDetalle("Escribe tu nombre para cambiar el estado.");
  try {
    const d = await api(`/api/incidencias/${encodeURIComponent(actual.proyecto)}/${encodeURIComponent(actual.id)}/estado`, {
      method: "PATCH", body: JSON.stringify({ estado: $("#d-estado").value, autor }),
    });
    pintarDetalle(d);
    toast(`Estado actualizado a ${ESTADOS[d.estado]}`);
    refrescar();
  } catch (e) {
    errorDetalle(e.message);
  }
});

$("#form-comentario").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  if (!form.checkValidity()) return errorDetalle("Escribe tu nombre (2+ letras) y el comentario.");
  try {
    const d = await api(`/api/incidencias/${encodeURIComponent(actual.proyecto)}/${encodeURIComponent(actual.id)}/comentarios`, {
      method: "POST", body: JSON.stringify({ autor: form.autor.value, texto: form.texto.value }),
    });
    form.texto.value = "";
    pintarDetalle(d);
    refrescar();
  } catch (e) {
    errorDetalle(e.message);
  }
});

$("#d-eliminar").addEventListener("click", async () => {
  if (!confirm(`¿Eliminar la incidencia «${actual.titulo}»?`)) return;
  try {
    await api(`/api/incidencias/${encodeURIComponent(actual.proyecto)}/${encodeURIComponent(actual.id)}`, { method: "DELETE" });
    $("#detalle").close();
    toast("Incidencia eliminada");
    refrescar();
  } catch (e) {
    errorDetalle(e.message);
  }
});

$("#d-cerrar").addEventListener("click", () => $("#detalle").close());

cargarEstado();
refrescar();
