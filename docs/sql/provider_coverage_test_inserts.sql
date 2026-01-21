-- Script de prueba para insertar registros adicionales en provider_coverage
-- Enfocado en proximidad geográfica para testing
-- Asume que los providers ya existen con IDs del 1 en adelante

-- Electricista en Concepción: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(6, 'Talcahuano'),
(6, 'San Pedro de la Paz'),
(6, 'Chiguayante'),
(6, 'Hualpén')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Gasfiter en Concepción: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(1, 'Talcahuano'),
(1, 'San Pedro de la Paz'),
(1, 'Chiguayante')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Electricista en Hualpén: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(7, 'Concepción'),
(7, 'Talcahuano'),
(7, 'San Pedro de la Paz')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Técnico computación en Concepción: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(16, 'Talcahuano'),
(16, 'San Pedro de la Paz'),
(16, 'Chiguayante'),
(16, 'Hualpén')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Mecánico en Concepción: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(21, 'Talcahuano'),
(21, 'San Pedro de la Paz'),
(21, 'Chiguayante')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Maestro en Chiguayante: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(11, 'Concepción'),
(11, 'San Pedro de la Paz'),
(11, 'Hualqui')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Gasfiter en Talcahuano: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(2, 'Concepción'),
(2, 'San Pedro de la Paz'),
(2, 'Hualpén')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Electricista en Los Ángeles: agregar comunas cercanas (región más amplia)
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(10, 'Nacimiento'),
(10, 'Negrete'),
(10, 'Cabrero')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Técnico computación en Talcahuano: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(17, 'Concepción'),
(17, 'San Pedro de la Paz'),
(17, 'Hualpén')
ON CONFLICT (provider_id, comuna) DO NOTHING;

-- Mecánico en Los Ángeles: agregar comunas cercanas
INSERT INTO provider_coverage (provider_id, comuna) VALUES
(23, 'Nacimiento'),
(23, 'Cabrero'),
(23, 'Yumbel')
ON CONFLICT (provider_id, comuna) DO NOTHING;