# Cómo hace alguien de Ecuador para usar Thinkuy (sin tocar tu PC)

> Escrito en lenguaje llano a propósito. Sin jerga.

## La respuesta corta

**Nadie entra a la base de tu PC. Nunca.**

En un servicio web hay **una sola base de datos, y vive en el servidor**. Los investigadores
abren una dirección en el navegador (por ejemplo `https://thinkuy.org/app/`) y trabajan ahí. Tu
computador no participa.

Y hay algo importante que quizá no sabías: **la herramienta ya funciona así**. Las búsquedas van
**en vivo** a OpenAlex, OpenAIRE y Dialnet desde donde esté el servidor. El catálogo de tu PC no
se usa para buscar: por eso un visitante de Ecuador obtiene los mismos resultados que tú. Tu base
solo guarda tus revisiones (cribados, fichas), que son **tuyas y privadas**.

Por eso corregí ayer que **buscar ya no escriba nada**: solo se guarda cuando tú transfieres
resultados a una revisión. Un visitante no puede ensanchar tu base por buscar.

---

## Paso 1 — Probar hoy desde otro dispositivo (5 minutos)

Sirve para ver con tus propios ojos que la herramienta es accesible desde fuera de tu PC.

1. Abre una consola en la carpeta del proyecto y arranca escuchando en la red:
   ```powershell
   $env:THINKUY_HOST = "0.0.0.0"
   .\backend\.venv\Scripts\python.exe .\backend\run_server.py
   ```
   La consola **imprime la dirección para otros equipos**, por ejemplo:
   ```
   Escuchando en: 0.0.0.0:8000
   Desde la red:  http://10.215.13.15:8000/app/
   ```
2. Permite el puerto en el cortafuegos (una vez, como Administrador):
   ```powershell
   New-NetFirewallRule -DisplayName "Thinkuy 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```
3. Desde el teléfono o desde otro computador **conectado al mismo wifi**, abre esa dirección.

Si abre, ya tienes un servidor funcionando: solo le falta estar en internet.

---

## Paso 2 — Que alguien de FUERA entre hoy (15 minutos)

Para una prueba puntual, un túnel público evita tener que contratar nada. Instala
[`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
o [`ngrok`](https://ngrok.com/download) y ejecuta, **con el servidor del Paso 1 encendido**:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Te devuelve una dirección pública del tipo `https://algo-aleatorio.trycloudflare.com`. Pásasela a
quien quieras: **desde Ecuador abrirá tu Thinkuy**. Es temporal y para probar, no para producción.

> Aviso honesto: mientras el túnel esté abierto, quien tenga la dirección puede usar la
> herramienta —y como todavía no hay usuarios separados, **vería tus protocolos**. Úsalo solo para
> una prueba corta y con datos que no te importe mostrar. Ver «Lo que falta» más abajo.

---

## Paso 3 — El despliegue de verdad (un servidor)

Ya dejé preparado lo necesario: `Dockerfile`, `docker-compose.yml` y `backend/requirements.txt`.
Docker empaqueta la herramienta entera para que funcione igual en cualquier servidor, sin
instalar Python ni nada a mano.

### 3.1. En un servidor (VPS) — recomendado

1. Contrata un servidor pequeño (2 GB de RAM bastan para empezar) con Ubuntu.
2. Copia el proyecto y crea el archivo `.env` con los secretos (**nunca al repositorio**):
   ```
   THINKUY_OPENALEX_API_KEY=...
   CORE_API_KEY=...
   THINKUY_CORS_ORIGINS=https://tudominio.org
   ```
3. Levanta el servicio:
   ```bash
   docker compose up --build -d
   ```
4. Pon un dominio con HTTPS delante (Cloudflare Tunnel, Caddy o Nginx). HTTPS no es opcional:
   los navegadores modernos y las buenas prácticas lo exigen.

**La base de datos queda en el volumen `./data` del servidor.** Actualizar el código no la toca.
Haz copia de seguridad de esa carpeta: es todo lo que hay que respaldar.

### 3.2. En tu PC, pero con Docker (para ensayar el despliegue)

Igual que arriba, con Docker Desktop instalado. Sirve para comprobar que el contenedor arranca
antes de pagar un servidor.

---

## Qué cambia para los investigadores

| Antes (local) | Ahora (servicio) |
| :--- | :--- |
| Cada uno instala Python, el entorno y los modelos | Abren una dirección y usan |
| Cada uno tiene su base en su PC | La base está en el servidor |
| Hay que ejecutar `inicio.bat` | Nada que ejecutar |
| Solo funciona en su computador | Funciona desde cualquier lugar |

---

## Lo que todavía falta para ser multiusuario de verdad

Lo digo sin adornos, porque es lo que hay:

1. **Usuarios separados.** Hoy los protocolos, cribados y fichas no tienen dueño: si dos personas
   usan la misma instancia, **se ven entre sí**. Es lo primero que hay que resolver antes de
   abrirla al público.
2. **Autenticación.** Aunque sea un enlace firmado o una clave de institución. Sin identidad no
   hay separación posible.
3. **El campo activo es global.** Cambiar de campo afecta a todos los usuarios de esa instancia
   (`db.set_db`); debe pasar a ser por usuario.
4. **Base de datos con concurrencia.** SQLite sirve para un puñado de usuarios; con muchos hará
   falta PostgreSQL.
5. **Renombrar la lógica que dice «catálogo local».** En un servicio, el catálogo no es «local»:
   es la memoria del servidor.

El inventario técnico completo, con la evidencia de cada punto, está en
[`DESPLIEGUE_MULTIUSUARIO.md`](DESPLIEGUE_MULTIUSUARIO.md).

---

## Errores que ya nos costaron tiempo (para no repetirlos)

* **No lances dos servidores a la vez.** SQLite no soporta bien dos escritores; el lanzador avisa
  si el puerto está ocupado.
* **No abras CORS con `*`** en un servicio público.
* **No metas secretos en el repositorio.**
* **No dejes la base dentro del código**: en contenedor va al volumen (`THINKUY_DATA_DIR`), o cada
  actualización la borra.
