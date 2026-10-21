import anthropic
import streamlit as st
from google import genai
from google.genai import errors as errores_gemini

from core import asistente, asistente_gemini
from core.asistente import Contexto
from core.muestreo import METODOS
from core.pruebas import REGISTRO
from ui import estado
from ui.artefactos import mostrar_artefacto

# Mismo agente con dos proveedores: Gemini (tiene nivel gratuito) y Claude.
PROVEEDORES = {
    "anthropic": {"nombre": "Claude (Anthropic)", "clave": "ANTHROPIC_API_KEY", "modulo": asistente,
                  "consola": "console.anthropic.com"},
    "gemini": {"nombre": "Gemini (Google)", "clave": "GEMINI_API_KEY", "modulo": asistente_gemini,
               "consola": "aistudio.google.com"},
}

conjunto = estado.requiere_datos()
st.title("Asistente de auditoría")
st.caption("Pregunta en español sobre tus datos. El asistente consulta, grafica, ejecuta pruebas del catálogo y "
           "propone hallazgos; tú decides qué fijar en un tablero o guardar en el registro.")

elegido = (estado.configuracion("DATAUDIT_PROVEEDOR") or "").strip().lower()
if elegido not in PROVEEDORES:
    # Sin preferencia explícita: Claude si hay clave de Anthropic; si no, Gemini.
    elegido = next((p for p in ("anthropic", "gemini") if estado.configuracion(PROVEEDORES[p]["clave"])), "")
api_key = estado.configuracion(PROVEEDORES[elegido]["clave"]) if elegido else None
if not api_key:
    st.info("Para usar el asistente agrega en `.streamlit/secrets.toml` (o en *Settings → Secrets* de Streamlit "
            "Cloud) una de estas claves y recarga la página:\n\n"
            "- `GEMINI_API_KEY`: Gemini de Google, con nivel gratuito. Créala en **aistudio.google.com**.\n"
            "- `ANTHROPIC_API_KEY`: Claude de Anthropic, de pago por uso. Créala en **console.anthropic.com**.",
            icon=":material/key:")
    st.stop()
proveedor = PROVEEDORES[elegido]
modulo = proveedor["modulo"]


@st.cache_resource
def cliente(nombre: str, clave: str):
    return anthropic.Anthropic(api_key=clave) if nombre == "anthropic" else genai.Client(api_key=clave)


esfuerzo = estado.configuracion("DATAUDIT_ESFUERZO", asistente.ESFUERZO_POR_DEFECTO)
if esfuerzo not in asistente.ESFUERZOS:
    esfuerzo = asistente.ESFUERZO_POR_DEFECTO
CLAVES_CHAT = ("chat_mensajes", "chat_vista", "chat_artefactos", "chat_uso", "chat_modelo")
# El historial tiene el formato de cada proveedor: si cambia el proveedor, empieza una conversación nueva.
if st.session_state.get("chat_proveedor") != elegido:
    for clave in CLAVES_CHAT:
        st.session_state.pop(clave, None)
    st.session_state["chat_proveedor"] = elegido
# Si en esta conversación ya se pasó a un modelo de respaldo, se sigue con él.
modelo = st.session_state.get("chat_modelo") or estado.configuracion("DATAUDIT_MODELO", modulo.MODELO_POR_DEFECTO)
st.session_state.setdefault("chat_mensajes", [])  # historial exacto que se envía a la API
st.session_state.setdefault("chat_vista", [])  # lo que se dibuja en pantalla
st.session_state.setdefault("chat_artefactos", {})
st.session_state.setdefault("chat_uso", {"entrada": 0, "salida": 0, "cache": 0, "pasos": 0})
artefactos = st.session_state["chat_artefactos"]

barra = st.columns([3, 1], vertical_alignment="center")
uso_total = st.session_state["chat_uso"]
resumen_uso = f"{proveedor['nombre']} · modelo {modelo}"
if uso_total["pasos"]:
    costo = asistente.costo_aproximado(modelo, uso_total)
    resumen_uso += (f" · {uso_total['entrada'] + uso_total['cache']:,} tokens de entrada, "
                    f"{uso_total['salida']:,} de salida".replace(",", ".")
                    + (f" · ≈ US$ {costo:.2f} en esta conversación" if costo is not None else ""))
barra[0].caption(resumen_uso)
if barra[1].button("Nueva conversación", icon=":material/add_comment:", disabled=not st.session_state["chat_vista"]):
    for clave in CLAVES_CHAT:
        st.session_state.pop(clave, None)
    st.rerun()


def describir_paso(nombre: str, entrada: dict) -> str:
    if nombre == "ver_esquema":
        return "Revisando las tablas y columnas disponibles"
    if nombre == "consultar_sql":
        return f"Consultando: {entrada.get('proposito') or 'datos'}"
    if nombre == "crear_grafica":
        return f"Graficando el resultado {entrada.get('resultado_id', '')}"
    if nombre == "ejecutar_prueba":
        prueba = REGISTRO.get(entrada.get("clave", ""))
        return f"Ejecutando la prueba «{prueba.nombre if prueba else entrada.get('clave')}» sobre {entrada.get('conjunto')}"
    if nombre == "seleccionar_muestra":
        return f"Seleccionando una muestra {METODOS.get(entrada.get('metodo'), '')} de {entrada.get('tamano')} elementos"
    if nombre == "proponer_hallazgo":
        return "Redactando un borrador de hallazgo"
    return nombre


def dibujar(partes: list[dict]) -> None:
    for parte in partes:
        if parte["tipo"] == "texto":
            st.markdown(parte["texto"])
        elif parte["tipo"] == "razonamiento":
            with st.expander("Razonamiento", icon=":material/psychology:"):
                st.markdown(parte["texto"])
        elif parte["tipo"] == "paso":
            st.caption(f":material/{parte.get('icono', 'build')}: {parte['texto']}")
        elif parte["tipo"] == "artefacto" and parte["id"] in artefactos:
            mostrar_artefacto(artefactos[parte["id"]])
        elif parte["tipo"] == "error":
            st.error(parte["texto"], icon=":material/error:")


class Transmision:
    """Dibuja los eventos del agente a medida que llegan y arma las partes para el historial."""

    def __init__(self):
        self.partes: list[dict] = []
        self.texto = ""
        self.razonamiento = ""
        self.marcador = st.empty()

    def _cerrar(self) -> None:
        if self.razonamiento.strip():
            self.partes.append({"tipo": "razonamiento", "texto": self.razonamiento})
            with self.marcador.container():
                with st.expander("Razonamiento", icon=":material/psychology:"):
                    st.markdown(self.razonamiento)
            self.marcador = st.empty()
        if self.texto.strip():
            self.partes.append({"tipo": "texto", "texto": self.texto})
            self.marcador.markdown(self.texto)
            self.marcador = st.empty()
        self.texto = self.razonamiento = ""

    def recibir(self, evento: asistente.Evento) -> None:
        if evento.tipo == "texto":
            if self.razonamiento:
                self._cerrar()
            self.texto += evento.texto
            self.marcador.markdown(self.texto + "▌")
        elif evento.tipo == "razonamiento":
            self.razonamiento += evento.texto
            self.marcador.caption(":material/psychology: " + self.razonamiento[-280:].replace("\n", " "))
        elif evento.tipo == "reinicio":
            self.texto = self.razonamiento = ""
            self.marcador.empty()
        else:
            self._cerrar()
            if evento.tipo == "herramienta":
                parte = {"tipo": "paso", "texto": describir_paso(evento.texto, evento.detalle)}
            elif evento.tipo == "error_herramienta":
                parte = {"tipo": "paso", "icono": "undo", "texto": f"Corrigiendo: {evento.texto}"}
            elif evento.tipo == "aviso":
                parte = {"tipo": "paso", "icono": "swap_horiz", "texto": evento.texto}
            elif evento.tipo == "artefacto":
                parte = {"tipo": "artefacto", "id": evento.artefacto.id}
            elif evento.tipo == "error":
                parte = {"tipo": "error", "texto": evento.texto}
            else:
                return
            self.partes.append(parte)
            with self.marcador.container():
                dibujar([parte])
            self.marcador = st.empty()


for entrada in st.session_state["chat_vista"]:
    with st.chat_message(entrada["rol"], avatar=":material/person:" if entrada["rol"] == "user" else
                         ":material/fact_check:"):
        dibujar(entrada["partes"])

if not st.session_state["chat_vista"]:
    st.markdown("**Prueba con:**")
    sugerencias = (
        "¿Cuáles son los 10 terceros con mayor valor y qué porcentaje del total representan?",
        "Muéstrame la evolución mensual del valor total en una gráfica.",
        "Ejecuta la ley de Benford y explícame qué debería revisar.",
        "¿Hay pagos duplicados? Si los hay, propón un hallazgo.",
    )
    columnas = st.columns(2)
    for i, sugerencia in enumerate(sugerencias):
        if columnas[i % 2].button(sugerencia, key=f"sug_{i}", width="stretch"):
            st.session_state["pregunta_pendiente"] = sugerencia
            st.rerun()

st.caption(f":material/lock: Al asistente ({proveedor['nombre']}) se envían tus preguntas, el esquema de las tablas, "
           f"hasta 3 valores de ejemplo por columna y como máximo {asistente.FILAS_AL_MODELO} filas de cada resultado; "
           "nunca el archivo completo.")
if elegido == "gemini":
    st.warning("En el nivel gratuito de Gemini, según los términos de Google, lo que envías puede usarse para mejorar "
               "sus productos. Úsalo con datos de demostración o anonimizados, no con información real de clientes.",
               icon=":material/policy:")

pregunta = st.chat_input(f"Pregunta sobre {conjunto.nombre} u otro conjunto cargado…")
pregunta = pregunta or st.session_state.pop("pregunta_pendiente", None)
if pregunta:
    st.session_state["chat_vista"].append({"rol": "user", "partes": [{"tipo": "texto", "texto": pregunta}]})
    st.session_state["chat_mensajes"].append(modulo.mensaje_usuario(pregunta))
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(pregunta)
    contexto = Contexto(estado.conjuntos(), estado.motor(), artefactos, st.session_state["activo"])
    with st.chat_message("assistant", avatar=":material/fact_check:"):
        transmision = Transmision()
        try:
            for evento in modulo.responder(cliente(elegido, api_key), st.session_state["chat_mensajes"], contexto,
                                           modelo, esfuerzo):
                transmision.recibir(evento)
                if evento.tipo in ("fin", "error") and evento.detalle:
                    for clave in uso_total:
                        uso_total[clave] += evento.detalle.get(clave, 0)
                    if evento.detalle.get("modelo", modelo) != modelo:
                        st.session_state["chat_modelo"] = evento.detalle["modelo"]
        except anthropic.AuthenticationError:
            transmision.recibir(asistente.Evento("error", "La API key de Anthropic no es válida. Revísala en "
                                                          "la configuración."))
        except anthropic.PermissionDeniedError:
            transmision.recibir(asistente.Evento("error", "Tu cuenta de Anthropic no tiene acceso a este modelo."))
        except anthropic.RateLimitError:
            transmision.recibir(asistente.Evento("error", "Se alcanzó el límite de uso de la API. Espera un momento "
                                                          "y vuelve a intentarlo."))
        except anthropic.APIConnectionError:
            transmision.recibir(asistente.Evento("error", "No hay conexión con Anthropic. Revisa tu internet."))
        except anthropic.APIStatusError as error:
            transmision.recibir(asistente.Evento("error", f"Error de la API de Anthropic ({error.status_code}): "
                                                          f"{error.message}"))
        except errores_gemini.ClientError as error:
            if error.code == 429:
                mensaje = ("Se alcanzó el límite del nivel gratuito de Gemini. Espera un minuto y vuelve a "
                           "intentarlo (los límites diarios se ven en aistudio.google.com).")
            elif error.code in (401, 403) or "API key" in str(error.message):
                mensaje = "La API key de Gemini no es válida o no tiene permiso. Revísala en aistudio.google.com."
            else:
                mensaje = f"Error de la API de Gemini ({error.code}): {error.message}"
            transmision.recibir(asistente.Evento("error", mensaje))
        except errores_gemini.ServerError as error:
            transmision.recibir(asistente.Evento("error", f"Gemini no está disponible en este momento ({error.code}). "
                                                          "Inténtalo de nuevo en unos minutos."))
    st.session_state["chat_vista"].append({"rol": "assistant", "partes": transmision.partes})
    st.rerun()
