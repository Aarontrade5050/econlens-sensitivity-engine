"""Compatibilidad con la versión de Python del despliegue.

Streamlit Cloud corre Python 3.11 y el entorno local es más nuevo, así que hay
sintaxis que compila acá y revienta en producción. El caso real: anidar
f-strings con la misma comilla (`f'...{f"{x['a']}"}...'`) solo es válido desde
3.12 (PEP 701), y pasó los 226 tests locales antes de tumbar el deploy.

`ast.parse(feature_version=(3, 11))` no sirve para esto: el cambio es del
tokenizer y no está cubierto por feature_version. La única verificación real es
compilar con el intérprete de esa versión.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PYTHON_DESPLIEGUE = "3.11"

# El launcher `py` solo existe en Windows; en Linux se busca el binario directo.
_LAUNCHER = shutil.which("py")
_DIRECTO = shutil.which(f"python{PYTHON_DESPLIEGUE}")


def _comando(archivo: Path) -> list[str] | None:
    if _LAUNCHER:
        return [_LAUNCHER, f"-{PYTHON_DESPLIEGUE}", "-m", "py_compile", str(archivo)]
    if _DIRECTO:
        return [_DIRECTO, "-m", "py_compile", str(archivo)]
    return None


def _fuentes() -> list[Path]:
    return sorted(
        p for p in [*(RAIZ / "src").glob("*.py"), *RAIZ.glob("*.py")]
        if "__pycache__" not in p.parts
    )


@pytest.mark.skipif(
    _comando(Path(__file__)) is None,
    reason=f"no hay Python {PYTHON_DESPLIEGUE} instalado para verificar",
)
@pytest.mark.parametrize("archivo", _fuentes(), ids=lambda p: p.name)
def test_source_compiles_on_deploy_python(archivo: Path):
    proceso = subprocess.run(
        _comando(archivo), capture_output=True, text=True, timeout=120
    )

    assert proceso.returncode == 0, (
        f"{archivo.name} no compila en Python {PYTHON_DESPLIEGUE} "
        f"(la versión de Streamlit Cloud):\n{proceso.stderr}"
    )
