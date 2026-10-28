from fpdf import FPDF
from datetime import date
from typing import List

class QuotePDF(FPDF):
    def header(self):
        pass
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

def generate_quote_pdf(quote, company, client, lines) -> bytes:
    pdf = QuotePDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Colors from company
    primary = company.primary_color if company and company.primary_color else "#0ea5e9"
    # Convert hex to rgb
    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    r, g, b = hex_to_rgb(primary)
    
    # En-tête entreprise
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, 210, 35, "F")
    pdf.set_y(8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, (company.name if company and company.name else "Prime Vision Solutions"), align="L")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(10, 18)
    pdf.cell(0, 5, f"{company.address or ''} {company.city or ''} {company.country or ''}".strip() or "Tunis, Tunisie", align="L")
    pdf.set_xy(10, 23)
    pdf.cell(0, 5, f"Tel: {company.phone or '+216 00 000 000'} | Email: {company.email or 'contact@primevisionsolutions.tn'}", align="L")
    if company and company.tax_id:
        pdf.set_xy(10, 28)
        pdf.cell(0, 5, f"Matricule Fiscal: {company.tax_id}", align="L")
    
    # Titre Devis
    pdf.set_y(42)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 12, "DEVIS", align="R")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 52)
    pdf.set_text_color(80, 80, 80)
    
    # Infos devis
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(10, 58, 190, 32, "F")
    pdf.set_xy(12, 60)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(45, 6, "Numero:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(50, 6, quote.number)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 6, "Date:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, quote.created_at.strftime("%d/%m/%Y") if quote.created_at else date.today().strftime("%d/%m/%Y"))
    
    pdf.set_xy(12, 67)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(45, 6, "Validite:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(50, 6, quote.valid_until.strftime("%d/%m/%Y") if quote.valid_until else "")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 6, "Devise:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, quote.currency or "TND")
    
    pdf.set_xy(12, 74)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(45, 6, "Statut:")
    pdf.set_font("Helvetica", "", 9)
    status_labels = {"draft": "Brouillon", "sent": "Envoye", "accepted": "Accepte", "refused": "Refuse", "expired": "Expire"}
    pdf.cell(50, 6, status_labels.get(quote.status, quote.status))
    
    # Client
    pdf.set_y(95)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 8, "CLIENT", align="L")
    pdf.set_draw_color(r, g, b)
    pdf.line(10, 103, 60, 103)
    pdf.set_y(105)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, client.company_name if client else "")
    pdf.set_font("Helvetica", "", 9)
    pdf.ln(4)
    if client:
        if client.address or client.city:
            pdf.cell(0, 5, f"{client.address or ''} {client.city or ''} {client.country or ''}".strip())
            pdf.ln(5)
        if client.email:
            pdf.cell(0, 5, f"Email: {client.email}")
            pdf.ln(5)
        if client.phone:
            pdf.cell(0, 5, f"Tel: {client.phone}")
            pdf.ln(5)
        if client.tax_id:
            pdf.cell(0, 5, f"MF: {client.tax_id}")
            pdf.ln(5)
    
    pdf.ln(4)
    if quote.title:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, f"Objet: {quote.title}")
        pdf.ln(8)
    
    # Tableau lignes
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    # Colonnes: Désignation, Qté, PU HT, Remise, TVA, Total HT
    col_widths = [78, 15, 22, 15, 15, 25, 20]  # total 190
    headers = ["Designation", "Qte", "P.U. HT", "Rem.", "TVA", "Total HT", "Total TTC"]
    x_start = 10
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1, align="C", fill=True)
    pdf.ln()
    
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 8)
    fill = False
    for line in lines:
        # Handle page break
        if pdf.get_y() > 270:
            pdf.add_page()
            # re-add header
            pdf.set_fill_color(r, g, b)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 8)
            for i, h in enumerate(headers):
                pdf.cell(col_widths[i], 8, h, border=1, align="C", fill=True)
            pdf.ln()
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("Helvetica", "", 8)
        
        total_ht_before_tax = line.quantity * line.unit_price * (1 - (line.discount_percent or 0)/100)
        total_ttc = total_ht_before_tax * (1 + (line.tax_rate or 0)/100)
        
        # Alternating row color
        if fill:
            pdf.set_fill_color(248, 250, 252)
        else:
            pdf.set_fill_color(255, 255, 255)
        
        # Designation can be long - truncate
        designation = line.name
        if line.description:
            designation += f" - {line.description[:60]}"
        if len(designation) > 45:
            designation = designation[:45] + "..."
        
        y_before = pdf.get_y()
        x_before = pdf.get_x()
        
        pdf.cell(col_widths[0], 7, designation, border=1, fill=fill)
        pdf.cell(col_widths[1], 7, f"{line.quantity:g} {line.unit}", border=1, align="C", fill=fill)
        pdf.cell(col_widths[2], 7, f"{line.unit_price:.2f}", border=1, align="R", fill=fill)
        pdf.cell(col_widths[3], 7, f"{line.discount_percent:.0f}%" if line.discount_percent else "-", border=1, align="C", fill=fill)
        pdf.cell(col_widths[4], 7, f"{line.tax_rate:.0f}%", border=1, align="C", fill=fill)
        pdf.cell(col_widths[5], 7, f"{total_ht_before_tax:.2f}", border=1, align="R", fill=fill)
        pdf.cell(col_widths[6], 7, f"{total_ttc:.2f}", border=1, align="R", fill=fill)
        pdf.ln()
        fill = not fill
    
    # Totaux
    pdf.ln(2)
    # Calculate totals
    subtotal = quote.subtotal or 0
    discount_amount = quote.discount_amount or 0
    tax_amount = quote.tax_amount or 0
    total = quote.total or 0
    
    # Box totals
    totals_x = 120
    pdf.set_x(totals_x)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_fill_color(248, 250, 252)
    pdf.cell(45, 7, "Sous-total HT:", border=1, fill=True, align="L")
    pdf.cell(35, 7, f"{subtotal:.2f} {quote.currency}", border=1, align="R")
    pdf.ln()
    pdf.set_x(totals_x)
    pdf.cell(45, 7, "Remise:", border=1, fill=True, align="L")
    pdf.cell(35, 7, f"-{discount_amount:.2f} {quote.currency}", border=1, align="R")
    pdf.ln()
    pdf.set_x(totals_x)
    pdf.cell(45, 7, "TVA:", border=1, fill=True, align="L")
    pdf.cell(35, 7, f"{tax_amount:.2f} {quote.currency}", border=1, align="R")
    pdf.ln()
    pdf.set_x(totals_x)
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(45, 8, "TOTAL TTC:", border=1, fill=True, align="L")
    pdf.cell(35, 8, f"{total:.2f} {quote.currency}", border=1, align="R", fill=True)
    pdf.ln()
    
    pdf.set_text_color(30, 30, 30)
    
    # Conditions
    if quote.terms or quote.notes:
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 6, "Conditions et notes:")
        pdf.ln(6)
        pdf.set_text_color(60, 60, 60)
        pdf.set_font("Helvetica", "", 8)
        text = ""
        if quote.terms:
            text += f"Conditions de paiement: {quote.terms}\n"
        if quote.notes:
            text += quote.notes
        pdf.multi_cell(0, 4, text)
    
    # Footer legal
    pdf.ln(5)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4, "Devis valable jusqu'à la date indiquée. Au-delà, nous consulter. Prix exprimés en Dinar Tunisien (TND). TVA 19% selon réglementation en vigueur. Ce document est généré par Prime CRM - Prime Vision Solutions.")
    
    # Signature placeholder
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(95, 6, "Signature du client:", align="L")
    pdf.cell(95, 6, "Cachet et signature:", align="R")
    pdf.ln(15)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 90, pdf.get_y())
    pdf.line(120, pdf.get_y(), 200, pdf.get_y())
    
    # fpdf2: pdf.output() returns bytearray when no dest given, convert to bytes
    out = pdf.output()
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, str):
        return out.encode('latin-1')
    return out
