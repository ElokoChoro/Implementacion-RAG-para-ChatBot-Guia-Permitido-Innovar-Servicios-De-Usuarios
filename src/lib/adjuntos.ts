import type { AdjuntoCargado, LimitesAdjunto } from '../types'

// Mismos nombres que backend/app/adjuntos/extraer.py, para que los mensajes coincidan.
const NOMBRES: Record<string, string> = { pdf: 'PDF', docx: 'DOCX', md: 'Markdown (.md)' }
const TIPOS_DATO: Record<string, [string, string]> = {
  RUT: ['RUT', 'RUT'],
  CORREO: ['correo', 'correos'],
  TELEFONO: ['teléfono', 'teléfonos'],
}

// «PDF o DOCX», «PDF, DOCX o Markdown (.md)».
export function nombresFormatos(formatos: string[]): string {
  const nombres = formatos.map((f) => NOMBRES[f] ?? f.toUpperCase())
  return nombres.length === 1 ? nombres[0] : `${nombres.slice(0, -1).join(', ')} o ${nombres[nombres.length - 1]}`
}

// Valor del atributo `accept` del selector de archivos: «.pdf,.docx».
export function aceptados(formatos: string[]): string {
  return formatos.map((f) => `.${f}`).join(',')
}

// Revisa en el navegador lo mismo que el backend antes de subir: formato y tamaño. Devuelve el
// error para la persona o null si el archivo se puede subir.
export function validarArchivo(archivo: File, limites: LimitesAdjunto): string | null {
  const formato = archivo.name.includes('.') ? archivo.name.split('.').pop()!.toLowerCase() : ''
  if (!limites.formatos.includes(formato)) {
    return `Solo puedo leer archivos ${nombresFormatos(limites.formatos)}. Guarda tu documento en uno de esos formatos y vuelve a subirlo.`
  }
  if (archivo.size === 0) {
    return 'El archivo está vacío. Revisa que sea el documento correcto y vuelve a subirlo.'
  }
  const mb = archivo.size / 1024 / 1024
  if (mb > limites.maxMb) {
    return `El archivo pesa ${mb.toFixed(1)} MB y el máximo es ${limites.maxMb} MB. Quítale imágenes o divídelo y vuelve a subirlo.`
  }
  return null
}

function datosReemplazados(reemplazos: Record<string, number>): string {
  const partes = Object.entries(reemplazos)
    .filter(([, n]) => n > 0)
    .map(([tipo, n]) => {
      const [uno, varios] = TIPOS_DATO[tipo] ?? [tipo.toLowerCase(), tipo.toLowerCase()]
      return `${n} ${n === 1 ? uno : varios}`
    })
  const total = Object.values(reemplazos).reduce((suma, n) => suma + n, 0)
  if (total === 0) {
    return 'No encontré RUT, correos ni teléfonos que reemplazar.'
  }
  return `Reemplacé ${total} ${total === 1 ? 'dato personal' : 'datos personales'} (${partes.join(', ')}) antes de procesarlo.`
}

// Mensaje del asistente cuando el adjunto quedó listo.
export function resumenAdjunto(a: AdjuntoCargado): string {
  const paginas = a.paginas ? `${a.paginas} ${a.paginas === 1 ? 'página' : 'páginas'}, ` : ''
  const minutos = Math.round(a.expira_en_s / 60)
  return [
    `Leí «${a.nombre}»: ${paginas}${a.fragmentos} ${a.fragmentos === 1 ? 'fragmento' : 'fragmentos'}.`,
    datosReemplazados(a.reemplazos),
    'Los nombres de personas todavía no se reemplazan.',
    `Por ahora solo lo leo: pronto podrás hacerme preguntas sobre él. Queda disponible ${minutos} minutos.`,
  ].join(' ')
}
