from agente_info import info


def test_info():
    result = info()
    assert "nombre" in result
    assert "version" in result
    assert "autor" in result
    assert result["nombre"] == "Davinci Agent"
    assert result["version"] == "1.0"
    assert result["autor"] == "Alex"
