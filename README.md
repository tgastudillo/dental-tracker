# dental-tracker

App en Streamlit para registrar tratamientos dentales y llevar un resumen de citas, usando Google Sheets como base de datos.

## Configuración inicial

1. Crea un entorno virtual e instala las dependencias:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Crea una Google Sheet llamada `DentalTracker` con dos pestañas:
   - `Catalogo`: columnas `Tratamiento` | `Precio`
   - `Citas`: columnas `Fecha` | `Cliente` | `Tratamientos` | `Total`

3. Configura las credenciales de Google:
   - Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml`.
   - Sigue las instrucciones dentro del archivo para crear una cuenta de servicio de Google Cloud y completar los valores.
   - Comparte la Google Sheet `DentalTracker` con el email de la cuenta de servicio (permiso de Editor).

4. Ejecuta la app:

   ```
   streamlit run app.py
   ```
