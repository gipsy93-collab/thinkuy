import urllib.request
import json
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

prompt = """Eres un metodólogo y cienciometrista experto. Tu labor es clasificar el artículo científico sobre Responsabilidad Social Universitaria (RSU) a partir de su abstract en una de las tres perspectivas canónicas de Duque & Cervantes (2019):
- P1_MEDICION_ESCALAS: Enfoque empírico cuantitativo, diseño o aplicación de escalas psicométricas, cuestionarios, análisis factorial (SEM) o baremos de medición propios.
- P2_ESTRATEGICO_STAKEHOLDERS: Enfoque de gobernanza institucional, políticas de dirección, modelos organizacionales, gestión estratégica o memorias de sostenibilidad frente a stakeholders.
- P3_CONEXION_SOCIAL_EXTENSION: Enfoque en ética civil, formación ciudadana, justicia social, derechos humanos, programas de aprendizaje-servicio o impacto comunitario directo.

Instrucción de formato:
Analiza el abstract cuidadosamente y emite ÚNICAMENTE un objeto JSON válido:
{
  "perspectiva": "P1_MEDICION_ESCALAS" o "P2_ESTRATEGICO_STAKEHOLDERS" o "P3_CONEXION_SOCIAL_EXTENSION",
  "justificacion": "explicación concisa de 15 a 25 palabras de la decisión metodológica",
  "claim_central": "tesis o aporte central del manuscrito"
}"""

user_msg = """Título: Developing university social responsibility: A model for the challenges of the new civil society
Abstract: The World Declaration on Higher Education in the Twenty-First Century drawn up at the World Conference of Higher Education organized by UNESCO in Paris in 1998, the Communication of the 2009 UNESCO World Conference on Higher Education, Paris, 2009 held in compliance with the guidelines of the 1998 Declaration and the list of objectives of the Bologna Process highlight that social responsibility is increasingly considered an intrinsic aspect of the higher education system, particularly of the universities. This paper aims to explain the shifting from Corporate Social University to University Social Responsibility, by presenting the conceptual framework of Social Responsibility and the university as a special type of organization which needs to adopt a social responsibility strategy just like the other organizations, in order to meet the expectations of the stakeholders (present students, future students, supporters etc). The paper presents, on the other hand, a general University Social Responsibility model in the context of globalization and develops a University Social Responsibility model considering the realities and challenges of the Romanian higher education system."""

req = urllib.request.Request(
    'http://127.0.0.1:1234/v1/chat/completions',
    data=json.dumps({
        'model': 'google/gemma-4-e2b',
        'messages': [
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': user_msg}
        ],
        'temperature': 0.1,
        'max_tokens': 800
    }).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

with urllib.request.urlopen(req, timeout=40) as resp:
    res = json.loads(resp.read().decode('utf-8'))['choices'][0]['message']
    print("=== PENSAMIENTO NATIVO DE GEMMA 4 ===")
    print(res.get('reasoning_content', ''))
    print("\n=== RESPUESTA (CONTENT) ===")
    print(res.get('content', ''))
