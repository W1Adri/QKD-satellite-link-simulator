# Este archivo lanza el servidor ASGI (Uvicorn) que ejecuta nuestra app FastAPI definida en `app/main.py`; lo usamos para arrancar con F5 en VS Code, en localhost:8000 y con recarga automática en desarrollo.

import uvicorn  # importamos el servidor ASGI que correrá FastAPI

def main():  # Función principal: prepara y arranca Uvicorn con la app de FastAPI ubicada en "app.backend:app" en 127.0.0.1:8000 con recarga.
    uvicorn.run(  # invoca el servidor
        "app.backend:app",  # ruta "modulo:objeto" de la app FastAPI
        host="127.0.0.1",  # escucha solo en local
        port=8000,  # puerto HTTP
        reload=True  # recarga automática al guardar
    )

if __name__ == "__main__":  # cuando ejecutamos este archivo directamente
    main()  # llama a la función principal
