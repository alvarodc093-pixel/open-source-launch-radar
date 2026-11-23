/** Forma de los JSON que genera `python -m radar.exportar`. */

export interface MetricasTest {
  mae_log: number;
  mediana_error_log: number;
  factor_error_tipico: number;
  spearman: number | null;
  dentro_de_x2: number;
  cobertura_90?: number;
}

export interface Arbol {
  izq: number[];
  der: number[];
  variable: number[];
  umbral: number[];
  valor: number[];
}

export interface ModeloJson {
  tipo: "mediana" | "ratio_tipico" | "ridge" | "gradient_boosting";
  numericas: string[];
  categoricas: string[];
  /** Categorías que el modelo distingue; el resto cuenta como «Otras». */
  categorias_modelo: string[];
  q90: number;
  metricas_test: MetricasTest;
  baselines_test: Record<string, MetricasTest>;
  cv_mae_log: Record<string, { mean: number; std: number }>;
  tamanos: { train: number; calibracion: number; test: number };
  mediana?: number;
  ratio?: { columna: string; desplazamiento: number };
  medianas?: Record<string, number>;
  medias?: Record<string, number>;
  escalas?: Record<string, number>;
  categorias?: Record<string, string[]>;
  ridge?: { coef: number[]; intercepto: number };
  gb?: { inicial: number; tasa: number; arboles: Arbol[] };
}

export interface Cuantiles {
  n: number;
  cuantiles: number[];
}

export type Propietario = "Persona" | "Organización";

export interface Ejemplo {
  paquete: string;
  nombre: string;
  fecha_lanzamiento: string;
  categoria: string;
  propietario_tipo: Propietario;
  dependencias: number;
  estrellas: number;
  lecturas: Record<string, { usuario: number; total: number; subidas: number }>;
  usuario_30d: number;
  total_30d: number;
  /** Descargas de usuario acumuladas, días 0 a 29. */
  acumuladas: number[];
  /** Descargas totales (con mirrors y bots) acumuladas, días 0 a 29. */
  acumuladas_total: number[];
}

/** Lo que necesita el buscador: el resto se pide al elegir el paquete. */
export type EjemploResumen = Pick<Ejemplo, "paquete" | "nombre" | "fecha_lanzamiento">;

export interface DatosRadar {
  generado_en: string;
  dias_lectura: number[];
  modelos: Record<string, ModeloJson>;
  cohortes: {
    cuantiles: number[];
    n_global: number;
    global: Record<string, number[]>;
    por_categoria: Record<string, { n: number } & Record<string, number[] | number>>;
  };
  curva_tipica: Record<string, number[]>;
  ejemplos: Ejemplo[];
  /** Por día de lectura y veredicto: dónde acabaron de verdad los paquetes del test. */
  aciertos_veredicto: Record<string, Record<string, AciertosVeredicto>>;
}

export interface AciertosVeredicto {
  por_encima: number;
  en_linea: number;
  por_debajo: number;
  /** «Por encima» que ya superaban el tercer cuartil el día de la lectura. */
  ya_superaba: number;
}

export interface DatosPrevio {
  generado_en: string;
  modelo: ModeloJson;
  cuantiles: number[];
  global: Cuantiles;
  por_categoria: (Cuantiles & { categoria: string })[];
  por_propietario: (Cuantiles & { propietario_tipo: Propietario })[];
  categoria_propietario: (Cuantiles & { categoria: string; propietario_tipo: Propietario })[];
}

export interface ContrasteEstrellas {
  repos: number;
  spearman: number;
  descargas_por_estrella: { mediana: number; q25: number; q75: number };
  por_categoria: { categoria: string; repos: number; spearman: number }[];
  /** Muchas estrellas y casi ninguna descarga: el caso que una métrica sola no ve. */
  mas_estrellas_que_uso: {
    paquete: string;
    repo: string;
    estrellas: number;
    usuario_30d: number;
  }[];
  mas_uso_que_estrellas: {
    paquete: string;
    repo: string;
    estrellas: number;
    usuario_30d: number;
  }[];
}

export interface DatosMercado {
  generado_en: string;
  embudo: Record<string, number>;
  paquetes_candidatos: number;
  paquetes_aptos: number;
  exclusiones: Record<string, number>;
  rango_lanzamientos: { desde: string; hasta: string };
  mediana_usuario_30d: number;
  mediana_total_30d: number;
  mediana_pct_usuario_30d: number;
  fraccion_mediana_del_mes: Record<string, number>;
  por_mes: { mes: string; lanzamientos: number; mediana_30d: number }[];
  por_categoria: { categoria: string; n: number; mediana_30d: number }[];
  por_propietario: { propietario_tipo: Propietario; n: number; mediana_30d: number }[];
  curva_tipica: number[];
  curva_tipica_total: number[];
  /** Cifras del EDA que enseña la portada (radar/eda.py). */
  hallazgos: Hallazgos;
  contraste_estrellas: ContrasteEstrellas;
}

export interface Hallazgos {
  spearman_7_30: number;
  spearman_total_subidas: number;
  spearman_usuario_subidas: number;
  descargas_por_subida: number;
  epsilon2: { categoria: number; propietario: number };
}

/** Entrada del radar tal como llega del formulario o de la API. */
export interface EntradaRadar {
  dia: number;
  usuario: number;
  total: number;
  subidas: number;
  dependencias: number;
  propietario_tipo: Propietario;
  categoria: string;
}

export interface EntradaPrevia {
  categoria: string;
  propietario_tipo: Propietario;
  dependencias: number;
  anios_cuenta: number | null;
  dias_repo_previos: number;
  mes_lanzamiento: number;
}
