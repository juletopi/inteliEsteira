"""Folhas A4 de etiquetas ArUco com medidas fisicas explicitas."""

from io import BytesIO

from vision.qrcode import ARUCO_PRINT_SIZES_MM, CameraDependencyError, generate_aruco_png
from core.classifier import STATE_TO_MACROREGION


def generate_aruco_pdf(product_id: str, marker_id: int, *, size_mm: int | None = 20) -> bytes:
    """Quatro copias do tamanho escolhido, ou os quatro tamanhos se size_mm=None."""
    if size_mm is not None and (type(size_mm) is not int or size_mm not in ARUCO_PRINT_SIZES_MM):
        raise ValueError("Escolha um tamanho ArUco de 20, 30, 40 ou 50 mm.")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise CameraDependencyError(
            "A biblioteca reportlab nao esta instalada. Execute pip install -r requirements.txt."
        ) from exc

    image = ImageReader(BytesIO(generate_aruco_png(marker_id)))
    sizes = ARUCO_PRINT_SIZES_MM if size_mm is None else (size_mm,) * 4
    output = BytesIO()
    page = Canvas(output, pagesize=A4, invariant=1)
    page.setTitle(f"ArUco - {product_id} - ID {marker_id}")
    page.setFont("Helvetica-Bold", 18)
    page.drawString(20 * mm, 275 * mm, "Etiquetas ArUco")
    page.setFont("Helvetica", 11)
    page.drawString(20 * mm, 266 * mm, f"Produto: {product_id}")
    page.setFont("Helvetica", 9)
    page.drawString(20 * mm, 258 * mm, f"ID {marker_id}  |  DICT_4X4_250  |  Mesmo produto em todas as etiquetas")

    for index, size in enumerate(sizes):
        center_x = (55 if index % 2 == 0 else 155) * mm
        center_y = (220 if index < 2 else 125) * mm
        side = size * mm
        x, y = center_x - side / 2, center_y - side / 2
        page.drawImage(image, x, y, width=side, height=side)
        # Marcas de corte ficam fora da margem branca da etiqueta.
        page.setStrokeColorRGB(0.65, 0.65, 0.65)
        page.setLineWidth(0.4)
        for corner_x, direction_x in ((x, -1), (x + side, 1)):
            for corner_y, direction_y in ((y, -1), (y + side, 1)):
                page.line(corner_x + direction_x * 2 * mm, corner_y,
                          corner_x + direction_x * 4 * mm, corner_y)
                page.line(corner_x, corner_y + direction_y * 2 * mm,
                          corner_x, corner_y + direction_y * 4 * mm)
        page.setFont("Helvetica-Bold", 10)
        page.drawCentredString(center_x, y - 7 * mm, f"{size} x {size} mm")
        page.setFont("Helvetica", 8)
        page.drawCentredString(center_x, y - 12 * mm, "Medida total, incluindo a margem branca")

    page.setFont("Helvetica-Bold", 10)
    page.drawString(20 * mm, 58 * mm, "Imprima em 100% / tamanho real.")
    page.setFont("Helvetica", 9)
    page.drawString(20 * mm, 52 * mm, 'Desative "ajustar a pagina" e confira a escala abaixo com uma regua.')
    page.setStrokeColorRGB(0, 0, 0)
    page.setLineWidth(0.7)
    page.line(20 * mm, 35 * mm, 70 * mm, 35 * mm)
    for tick in range(0, 51, 10):
        page.line((20 + tick) * mm, 33 * mm, (20 + tick) * mm, 37 * mm)
    page.setFont("Helvetica", 9)
    page.drawString(20 * mm, 27 * mm, "Conferencia: a linha acima deve medir 50 mm.")
    page.showPage()
    page.save()
    return output.getvalue()


def generate_aruco_batch_pdf(products: list[dict], *, size_mm: int | None = 20) -> bytes:
    """Uma etiqueta por produto/tamanho, com identificacao e paginacao A4."""
    if not products or size_mm is not None and (type(size_mm) is not int or size_mm not in ARUCO_PRINT_SIZES_MM):
        raise ValueError("Informe produtos e um tamanho de 20, 30, 40 ou 50 mm.")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise CameraDependencyError(
            "A biblioteca reportlab nao esta instalada. Execute pip install -r requirements.txt."
        ) from exc

    region_names = {"NORTE": "Norte", "SUL": "Sul", "SUDESTE": "Sudeste",
                    "NORDESTE": "Nordeste", "CENTRO_OESTE": "Centro-Oeste"}
    sizes = ARUCO_PRINT_SIZES_MM if size_mm is None else (size_mm,)
    entries = [(product, size) for product in products for size in sizes]
    largest = max(sizes)
    columns = int(180 // max(60, largest + 12))
    column_width = 180 * mm / columns
    row_height = (largest + 28) * mm
    rows = int(242 * mm // row_height)
    capacity = columns * rows
    page_count = (len(entries) + capacity - 1) // capacity
    output = BytesIO()
    page = Canvas(output, pagesize=A4, invariant=1)
    page.setTitle("Etiquetas ArUco em lote")
    images = {}
    for index, (product, size) in enumerate(entries):
        slot = index % capacity
        if slot == 0:
            if index:
                page.showPage()
            page.setFont("Helvetica-Bold", 16)
            page.drawString(15 * mm, 281 * mm, "Etiquetas ArUco em lote")
            page.setFont("Helvetica", 9)
            page.drawString(15 * mm, 274 * mm, f"{len(products)} produtos | {len(entries)} etiquetas | Medida total com margem branca")
            page.drawRightString(195 * mm, 281 * mm, f"Página {index // capacity + 1} de {page_count}")
            page.setFont("Helvetica", 8)
            page.drawString(15 * mm, 18 * mm, "Imprima em 100% / tamanho real. Não ajuste à página.")
            page.setStrokeColorRGB(0, 0, 0)
            page.setLineWidth(0.5)
            page.line(140 * mm, 18 * mm, 190 * mm, 18 * mm)
            page.line(140 * mm, 16 * mm, 140 * mm, 20 * mm)
            page.line(190 * mm, 16 * mm, 190 * mm, 20 * mm)
            page.drawCentredString(165 * mm, 12 * mm, "Referência: 50 mm")

        column, row = slot % columns, slot // columns
        center_x = 15 * mm + (column + 0.5) * column_width
        side = size * mm
        x = center_x - side / 2
        y = 267 * mm - row * row_height - side
        marker_id = product["aruco_id"]
        if marker_id not in images:
            images[marker_id] = ImageReader(BytesIO(generate_aruco_png(marker_id)))
        page.drawImage(images[marker_id], x, y, width=side, height=side)
        page.setStrokeColorRGB(0.65, 0.65, 0.65)
        page.setLineWidth(0.4)
        for corner_x, direction_x in ((x, -1), (x + side, 1)):
            for corner_y, direction_y in ((y, -1), (y + side, 1)):
                page.line(corner_x + direction_x * 2 * mm, corner_y,
                          corner_x + direction_x * 4 * mm, corner_y)
                page.line(corner_x, corner_y + direction_y * 2 * mm,
                          corner_x, corner_y + direction_y * 4 * mm)

        # Identificadores de ate 64 caracteres quebram em linhas, sem truncar.
        lines, current = [], ""
        for character in f"Produto: {product['id']}":
            if current and stringWidth(current + character, "Helvetica-Bold", 8.5) > column_width - 6 * mm:
                lines.append(current)
                current = ""
            current += character
        lines.append(current)
        label_y = y - 5 * mm
        page.setFont("Helvetica-Bold", 8.5)
        for line in lines:
            page.drawCentredString(center_x, label_y, line)
            label_y -= 3.4 * mm
        region = region_names[STATE_TO_MACROREGION[product["uf"]].value]
        page.setFont("Helvetica", 8.5)
        page.drawCentredString(center_x, label_y - 0.3 * mm, f"Região: {region} ({product['uf']})")
        page.setFont("Helvetica", 7.5)
        page.drawCentredString(center_x, label_y - 4 * mm, f"ArUco ID {marker_id} | {size} x {size} mm")
    page.showPage()
    page.save()
    return output.getvalue()
