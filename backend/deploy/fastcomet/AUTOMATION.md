# Actualizaciones del backend en FastComet

El workflow `.github/workflows/deploy-fastcomet.yml` se puede ejecutar manualmente
desde **Actions → Deploy backend to FastComet → Run workflow**. También se ejecuta
al publicar una release estable de GitHub, usando el commit de su etiqueta.
No se ejecuta en cada push ni al publicar una prerelease.

## Configuración inicial

La aplicación debe estar creada y funcionando según [README.md](README.md).
Se necesitan SSH con autenticación por clave, Bash, `flock`, `tar`, `curl` y el
Python del entorno virtual de cPanel con pip. No requiere sudo ni rsync.

Crear el environment **fastcomet-production** en GitHub y añadir estas variables:

| Variable | Valor |
|---|---|
| `FASTCOMET_HOST` | Host SSH del servidor, sin `https://` |
| `FASTCOMET_USER` | Usuario cPanel |
| `FASTCOMET_PORT` | En esta cuenta, configurar `22`; el script usa `17177` si se omite |
| `FASTCOMET_APP_ROOT` | Ruta absoluta de Application root; copiar la real de cPanel |
| `FASTCOMET_PYTHON` | Ruta absoluta al `bin/python` del entorno virtual de la aplicación |
| `FASTCOMET_HEALTH_URL` | `https://api.social-media-marketing.ai4l.com.au/api/health/ready` (sin query string) |

Si cPanel muestra `source /home/USUARIO/virtualenv/RUTA/3.12/bin/activate`, el
intérprete correspondiente es `/home/USUARIO/virtualenv/RUTA/3.12/bin/python`.
No hace falta activar el entorno: se ejecuta ese intérprete directamente.

Añadir estos **secrets** en el mismo environment:

| Secret | Contenido |
|---|---|
| `FASTCOMET_SSH_PRIVATE_KEY` | Bloque completo de la clave privada dedicada al despliegue; autorizar su clave pública en cPanel |
| `FASTCOMET_SSH_PASSPHRASE` | Passphrase de esa clave; omitir si la clave no está cifrada |
| `FASTCOMET_SSH_KNOWN_HOSTS` | Entrada verificada de `known_hosts`, incluyendo `[HOST]:PUERTO` si el puerto no es 22 |

Obtener la clave del host con `ssh-keyscan -p 22 HOST` y verificar su huella
con FastComet o con una conexión de confianza antes de guardarla. El script exige
`StrictHostKeyChecking=yes`; no acepta automáticamente un host desconocido.

El workflow desbloquea la clave mediante `SSH_ASKPASS` y la carga en un agente SSH
temporal durante un máximo de 30 minutos. La passphrase solo está disponible en
el paso de configuración; no se escribe en archivos ni se pasa como argumento.
El archivo temporal de la clave se elimina después de cargarla y el agente se
cierra al terminar el job. También se admiten claves sin passphrase.
Si el desbloqueo falla, el despliegue se detiene antes de conectar al servidor.
Esto utiliza el mecanismo de [OpenSSH ssh-add](https://man.openbsd.org/ssh-add).

### Si aparece Permission denied

Ejecutar un **Run workflow nuevo** sobre la rama que contiene estos cambios.
Reintentar un run anterior no incorpora cambios de código posteriores.
El paso **Verify SSH authentication** imprime el commit, el puerto y la huella
pública de la clave cargada; también registra qué clave ofrece SSH al servidor.
No imprime la clave privada ni la passphrase. Se detiene antes de transferir
archivos si no puede autenticarse y ejecutar un comando remoto.

Si la clave está cargada y el servidor la rechaza, comprobar que su clave pública
esté **Authorized** en cPanel para `FASTCOMET_USER`. No basta con importarla.
La clave autorizada debe corresponder a la privada del secret de GitHub.
Si no hay claves cargadas, revisar el paso **Configure SSH** y el commit del run.

El servidor debe tener `.env` en Application root, con `APP_ENV=production`,
`DATABASE_URL` y la configuración completa de producción. Las variables de
**Setup Python App** no se heredan al abrir SSH: deben coincidir con este archivo
si están definidas también allí. El workflow no recibe ni copia `.env`.

Guardar estos cambios en GitHub antes de ejecutar el workflow. El paquete siempre
se construye desde archivos **committed** de `HEAD`, nunca desde cambios locales.

## Qué hace

1. Comprueba los scripts con pruebas aisladas y transfiere por SCP un tar del backend.
2. Toma un bloqueo en el servidor y guarda el código anterior y `pip freeze` en
   `~/.local/state/wrcc-deploy/<fecha>-<commit>.<id>/`, fuera de Application root.
3. Instala `requirements.txt` en el entorno Python existente y ejecuta `pip check`.
4. Valida la configuración y ejecuta `python -m alembic -c alembic.ini upgrade head`
   desde el código nuevo, usando el `.env` del servidor. No ejecuta el seed de admin.
5. Reemplaza únicamente `app/`, `migrations/`, `alembic.ini`, `passenger_wsgi.py`,
   `bootstrap.py`, `requirements.txt` y `.deploy-release`. Conserva `.env`,
   `.htaccess`, `media/`, logs y otros archivos del hosting.
6. Actualiza `tmp/restart.txt` y consulta readiness hasta que PostgreSQL esté
   disponible **y** el header `X-WRCC-Release` corresponda al commit desplegado.
   El header se carga al arrancar el proceso, por lo que un worker anterior no
   puede dar por bueno el despliegue. La espera es de unos seis minutos como máximo.

El reinicio utiliza el mecanismo documentado de Passenger. Hay que comprobarlo
en la primera ejecución contra el LSAPI de este hosting: si no lo respeta, el
workflow falla esperando el commit nuevo y hará falta el mecanismo de reinicio
específico de cPanel. No se ha validado todavía contra el servidor real.

## Fallos y recuperación

Una instalación o migración fallida detiene el despliegue antes de reemplazar el
código. Pip usa el entorno compartido existente: puede haber modificado paquetes
aunque falle. Las migraciones aplicadas tampoco se deshacen automáticamente.

La sustitución de archivos no es atómica; puede haber una breve interrupción.
Las migraciones deben ser compatibles con los workers de la versión anterior
mientras se aplica la actualización. Hacer una copia de PostgreSQL antes de una
migración destructiva: el backup de este flujo contiene **código, no la base**.

Si falla la activación o readiness, el job queda en rojo e indica la carpeta de
recuperación. Los backups se conservan hasta retirarlos manualmente. No se
reintenta automáticamente ni se ejecuta `alembic downgrade`.

Para recuperar una versión, revisar primero la compatibilidad del esquema y las
dependencias. `code.tar.gz` contiene los archivos anteriores; `replaced/` contiene
los originales que alcanzaron a moverse durante la activación. Restaurar solo los
siete paths administrados (retirar antes sus versiones nuevas para no dejar módulos
obsoletos), reinstalar las dependencias compatibles, reiniciar desde cPanel y
comprobar `/api/health/ready`. `requirements-before.txt` es el inventario de versiones
previas, no una copia del entorno ni una garantía de recuperación de paquetes.

## Ejecutar sin GitHub Actions

Desde Linux o WSL, exportar las seis variables anteriores, configurar la clave SSH
y `known_hosts`, y ejecutar desde una copia del repositorio:

```bash
bash backend/deploy/fastcomet/deploy.sh
```

Para probar la secuencia sin conectar al hosting ni a una base de datos:

```bash
bash backend/deploy/fastcomet/test-deploy.sh
```

Fuentes: [SSH de FastComet](https://www.fastcomet.com/kb/free-ssh-access-with-all-hosting-packages),
[reinicio de Passenger](https://www.phusionpassenger.com/docs/advanced_guides/troubleshooting/standalone/restart_app.html),
[eventos de GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
