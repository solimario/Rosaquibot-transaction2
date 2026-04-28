import pandas as pd
import re
import os
import sys

# Leer variables de entorno
path = os.getenv("OUTPUT_XLS")
path_csv = os.getenv("OUTPUT_CSV")

# Validación
if not path or not path_csv:
    print("❌ ERROR: Las variables OUTPUT_XLS y OUTPUT_CSV no están definidas.")
    sys.exit(1)

# Leer archivo Excel
df = pd.read_excel(path)

# Eliminar filas y columnas innecesarias
df.drop(df.index[0:11], inplace=True)
df = df.drop(columns=df.columns[[0, 2, 4, 5, 6, 7, 9, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]])
df = df.dropna(subset=[df.columns[1]])

# Detectar período sin movimientos antes de procesar fechas
# (Crystal Reports devuelve XLS válido pero vacío cuando no hay datos)
columnas_ordenadas = [
    "origen_nombre", "origen_numero", "origen_categoria",
    "destino_nombre", "destino_numero", "destino_categoria",
    "tipo", "producto", "monto", "Fecha", "Hora"
]
if df.empty:
    pd.DataFrame(columns=columnas_ordenadas).to_csv(path_csv, index=False, encoding='utf-8')
    print("⚠️  Sin movimientos en el período. CSV generado vacío.")
    sys.exit(0)

# Separar fecha y hora
new_columns = df.iloc[:, 3].str.split(' ', expand=True)
df['Fecha'] = pd.to_datetime(new_columns[0], format='%d/%m/%y').dt.strftime('%Y-%m-%d')
df['Hora'] = new_columns[1]
df.drop(columns=[df.columns[3]], inplace=True)

# Función para extraer nombre y número
def extraer_nombre_numero(texto):
    if isinstance(texto, str):
        matches = re.findall(r'\((\d{6,})\)', texto)
        if matches:
            numero = matches[-1]  # último paréntesis con número
            nombre = texto.rsplit('(', 1)[0].strip()
            return nombre, numero
    return texto, ''

# Extraer origen_nombre y origen_numero
df[['origen_nombre', 'origen_numero']] = df['Unnamed: 1'].apply(
    lambda x: pd.Series(extraer_nombre_numero(x)))

# Extraer destino_nombre y destino_numero
df[['destino_nombre', 'destino_numero']] = df['Unnamed: 3'].apply(
    lambda x: pd.Series(extraer_nombre_numero(x)))

# Renombrar otras columnas
df.rename(columns={
    "Unnamed: 8": "tipo",
    "Unnamed: 11": "producto",
    "Unnamed: 12": "origen_categoria",     # antes Emisor
    "Unnamed: 13": "destino_categoria",    # antes Destinatario
    "Unnamed: 14": "monto"
}, inplace=True)

# Reordenar columnas
df = df[columnas_ordenadas]

# Guardar CSV
df.to_csv(path_csv, index=False, encoding='utf-8')
print("✅ CSV generado correctamente.")

