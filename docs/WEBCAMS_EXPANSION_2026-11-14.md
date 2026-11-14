# Q-Globe: seconda espansione mondiale delle webcam

Build del 14 novembre 2026, ore 02:57 UTC. Confronto con il catalogo di 33.991 record nel commit `4929dac74a8ff796d0203c4412f3a3ada50e60e9`.

> **Correzione del 14 novembre (filtro privacy).** I dati del pacchetto non erano pubblicabili: 9 record con credenziali nella query (un FRITZ!Box con `usr`/`pwd`, otto flussi ZoneMinder con `user`/`pass`), indirizzi DNS dinamici di reti domestiche e percorsi diretti di dispositivi (axis-cgi, cgi-bin/nph-zms, GetData.cgi, /record/current.jpg, mjpg/video). Il catalogo pubblicato è ricostruito offline con il filtro descritto in «Filtro privacy»: **62.527 record** (180 rimossi), 70.253 URL distinti. I numeri sotto descrivono il pacchetto prima del filtro.

## Risultato e stato di pubblicazione

Il database di lavoro contiene **62.707 record**, **50.840 URL primari distinti** e **70.428 URL pubblicati distinti**, provenienti da **81 fonti**. L'aggiornamento aggiunge **28.716 record e 31.762 URL distinti**, preservando tutti i record, gli URL e gli stati di verifica del catalogo precedente.

La copertura resta di **77 codici paese/territorio conosciuti**, più **323 record con paese non assegnato (`ZZ`)**. Questa espansione aumenta la copertura entro i paesi già presenti. Record, viste, posizioni associate e dispositivi fisici non sono quantità equivalenti. Il catalogo non costituisce un censimento completo di tutte le webcam del mondo.

SQLite, il catalogo del viewer e il codice sono aggiornati e verificati nella copia di lavoro. **Il repository remoto e il globo online non sono stati pubblicati:** questa sessione non dispone di un push Git autenticato. Il pacchetto comprende dati e patch cumulativa applicabili da un ambiente autenticato; non equivale a una distribuzione online già completata.

| Misura | Prima | Dopo | Variazione |
| --- | ---: | ---: | ---: |
| Record pubblicati | 33.991 | 62.707 | +28.716 |
| Fonti | 35 | 81 | +46 |
| URL primari distinti | 29.617 | 50.840 | +21.223 |
| Tutti gli URL distinti, riferimenti compresi | 38.666 | 70.428 | +31.762 |
| URL con percorso `.m3u8` | 2.918 | 9.550 | +6.632 |
| HLS abilitati nel player | 2.446 | 2.446 | 0 |
| HLS conservati solo come riferimenti | 472 | 7.104 | +6.632 |
| Record snapshot | 12.728 | 13.011 | +283 |
| Record con collegamento esterno | 18.810 | 47.243 | +28.433 |

I 2.446 endpoint HLS del player corrispondono a 2.453 record. Gli ulteriori HLS mantengono i diritti dei gestori e non sono stati trasformati in permessi di riproduzione. La presenza dell'estensione `.m3u8` non dimostra disponibilità, freschezza, compatibilità o autorizzazione all'embed. Restano inoltre 900 URL di clip MP4, classificati separatamente dalla diretta continua.

## Nuove acquisizioni

| Gruppo | Record aggiunti | Contenuto e trattamento |
| --- | ---: | --- |
| Giappone, Malaysia, Indonesia e SAAO | 13.074 | MLIT 11.307; LLM 486; BPJT 1.277; SAAO 4. Collegamenti pubblici e riferimenti, senza embed automatico. |
| Sette cataloghi USA | 9.767 | Iowa 1.261, Wisconsin 461, Illinois 3.859, Texas 3.170, Alabama 642, Baton Rouge 118, Kentucky 256. |
| Live Environment Streams, famiglie selezionate | 3.903 | VDOT, MnDOT, Seattle, Louisiana, Hawaii, Thailandia, Keelung e 13 reti comunali indonesiane. Metadati del repository con attribuzione; diritti media separati. |
| Europa | 1.129 | Via Lietuva, Euskadi, TrafficWatchNI, CHMI, Bizkaia, Fiandre, Vitoria-Gasteiz, Catalunya, Ginevra e Anglet. |
| Ottawa | 432 | Posizioni degli incroci; una mappa pubblica condivisa, senza inventare URL individuali. |
| FAA via LiveTrafficCam | 289 | Pagine pubblicate con ID sito e camera; attribuzione FAA, nessuna immagine importata. |
| AviationWX | 111 | 105 snapshot dell'operatore e 6 riferimenti a camere partner. Coordinate dell'aeroporto. |
| GeoNet | 11 | Snapshot vulcanologici, licenza delle immagini esplicita e timestamp del catalogo conservato. |
| **Totale** | **28.716** | |

I 283 nuovi snapshot provengono da TrafficWatchNI (127), Vitoria-Gasteiz (40), AviationWX (105) e GeoNet (11).

Gli URL non vengono moltiplicati per il numero di viste. Per esempio, Ottawa aggiunge 432 record ma una sola mappa pubblica principale; TxDOT pubblica 24 pagine di distretto più il portale generale usato per Lufkin. Iowa contiene 1.261 viste e 862 identificativi di dispositivo; Illinois 3.859 viste e 1.455 ID camera. In totale 12.332 record condividono un URL principale, distribuiti in 465 gruppi.

I paesi con più record nell'intero catalogo sono USA (24.545), Giappone (11.890), Canada (3.997), Taiwan (3.616), Finlandia (2.310), Indonesia (2.017), Spagna (1.649), Regno Unito (1.396), Germania (1.302), Austria (1.232), Norvegia (1.133) e Francia (1.069). La distribuzione completa è nel CSV dei paesi.

## Ricerca, provenienza e diritti

La ricerca ha confrontato cataloghi governativi, documentazione API, termini dei gestori e repository a commit fissati. Gli aggregatori servono anche a individuare l'operatore originale; la licenza del software non viene applicata automaticamente ai video indicizzati.

- **Live Environment Streams:** commit `462171be74a94963277dd76c8b2f8cd18f928cda`, versione 4.0.0. Il file acquisito ha 6.903 righe in 26 famiglie e sei paesi. Sono ammesse solo 20 famiglie valutate, con host espliciti; le famiglie già rappresentate da fonti ufficiali più complete vengono escluse e due URL già presenti non vengono aggiunti. La licenza CC BY 4.0 riguarda i metadati del dataset. Lo stato live dichiarato dall'aggregatore rimane un campo upstream, senza effetti su `health`.
- **traffic-camera-sources / LiveTrafficCam:** commit `d72090d56ae33d70ba28ef931fb8c229a8474beb`. Il GeoJSON acquisito contiene 1.906 righe, non decine di migliaia di endpoint completi. Il repository distingue la licenza dei file redatti da quella dei dati generati. Sono importati 289 riferimenti FAA con attribuzione dell'agenzia, senza attribuire loro una licenza CC BY generale.
- **Open-Eagle-Eye:** commit `beca204d9a048427833a3ed1ffa67d3fc27f60ec`, 30.758 righe nel file acquisito. Utilizzato per individuare fonti, non importato integralmente: contiene famiglie con diritti, accessi e condizioni differenti. La licenza MIT del repository non autorizza ogni media elencato.
- **MLIT Giappone:** conservati attribuzione e avviso di normalizzazione. I termini vietano raccolte automatiche periodiche dal sito; questa acquisizione non configura un polling ricorrente. Per la distribuzione continuativa occorre il canale indicato dal gestore.
- **Malaysia LLM:** la base dichiarata è la politica generale open data pubblicata da LLM, non una licenza specifica del layer CCTV inventata. Le immagini restano riferimenti esterni.
- **Ottawa:** i dati della mappa sono pubblici; l'accesso alle immagini richiede la registrazione prevista dal servizio. Nessun endpoint immagini autenticato è stato interrogato.
- **Illinois:** i metadati adattati mantengono CC BY-SA 2.0 e attribuzione; i diritti delle immagini restano separati. Nessuna licenza unica viene attribuita all'intero database multiforme.
- **GeoNet, AviationWX, TrafficWatchNI e Vitoria:** le autorizzazioni pubblicate per i rispettivi dati/immagini supportano gli snapshot ammessi, mantenendo le condizioni, le attribuzioni e gli intervalli di aggiornamento applicabili.

Fonti primarie principali:

- https://www.river.go.jp/kawabou/kwb_apend/html/caution.html
- https://www.geonet.org.nz/policy
- https://www.geonet.org.nz/data/types/camera
- https://api.aviationwx.org/
- https://www.trafficwatchni.com/twni/crown-copyright
- https://www.vitoria-gasteiz.org/wb021/was/contenidoAction.do?idioma=en&uid=app_j34_0202
- https://traffic.ottawa.ca/en/opendata
- https://iowadot.gov/policies-statements/terms-use
- https://github.com/william-ricchiuti/Live-Environment-Streams
- https://bzsasson.github.io/traffic-camera-sources/api.html

Le policy complete conservano `terms_url`, `metadata_license`, `media_rights`, `attribution`, host ammessi e decisione di revisione. Le ricevute riportano URL, orario e SHA-256. Il pacchetto esclude media, risposte contenenti camere non pubbliche, credenziali e copie integrali non necessarie di pagine/JavaScript dei gestori.

## Correzioni concrete

**Riferimenti secondari conservati.** `reference_hls_url` e `reference_snapshot_url` sono ora validati, esportati in SQLite/CSV e inclusi nella proiezione del viewer. Prima un record con HLS e immagine poteva conservare il secondo indirizzo soltanto nel JSON completo. I 70.428 URL includono entrambi quando pubblicati.

Il dettaglio del globo espone **16.234 riferimenti aggiuntivi su 14.432 record**, deduplicati rispetto a pagina principale e media primario. Sul web l'apertura richiede un clic; nell'app gli indirizzi sono selezionabili. I riferimenti non diventano video incorporabili e non passano al bridge nativo. Non si effettuano richieste ai gestori durante la preparazione del catalogo.

**Filtri URL coerenti.** Gli URL pubblici con porte valide non standard, come gli HLS Iowa su 8888, restano riferimenti consultabili. Questa eccezione non amplia gli host o le porte ammessi ai media attivi. Sono esclusi credenziali nell'URL, indirizzi IP, nomi locali/interni, porte non valide, host codificati con percentuali e aggregatori di camere non autorizzate.

**Identità distinte.** In Malaysia due record con stesso ID camera e coordinate pubblicano `CAM_14` e `CAM_15`: rimangono entrambi. Sono eliminate solo due coppie di duplicati esatti. FAA mantiene 289 viste in 148 posizioni; non si fondono camere per il semplice fatto che condividano coordinate o un URL.

**Coordinate documentate.** GeoNet pubblica coppie nell'ordine latitudine/longitudine; l'adapter corregge esplicitamente l'ordine per GeoJSON e conserva l'originale. I timestamp NZDT/NZST sono convertiti in UTC senza assumere un fuso non dichiarato. Ginevra usa l'output EPSG:4326 del servizio ufficiale; le Fiandre usano la trasformazione documentata da EPSG:3857. Le coordinate aeroportuali e degli incroci restano luoghi associati, non punti di installazione precisi.

**Datum non dichiarati.** TxDOT e ALGO (3.812), BPJT (1.277), parte dell'Europa (1.009), SAAO (4) e i 259 record Queensland preesistenti mantengono il CRS di origine o la sua incertezza. In GeoJSON **6.361 geometrie sono `null`**, con coordinate originali nelle proprietà: non vengono presentate come WGS84 già trasformato. Il globo conserva le posizioni indicative e la relativa qualifica. Gli insiemi esclusi per ruolo approssimativo e per datum incerto si sovrappongono, quindi i loro conteggi non vanno sommati.

## Esclusioni che evitano di gonfiare il catalogo

- Gdynia: 35 liste immagini vuote e catalogo con date 2018; un record ha coordinate errate. I 34 candidati rimanenti sono documentati ma non importati.
- Fiandre: i 74 endpoint AJAX di dettaglio sono evidenza tecnica, non 74 nuove pagine o video. Rimane il link alla directory ufficiale.
- ALGO: esclusi otto record con livelli Hidden/ALDOT/FirstResponder; ammessi soltanto 642 `Public`.
- BPJT: escluse 253 righe con coordinate non utilizzabili; sei valori RTSP con userinfo sono redatti nelle copie distribuibili e mai utilizzati.
- Euskadi: 159 righe metriche senza CRS sono sostituite dalla fonte diretta Bizkaia; 18 vecchie viste Vitoria dalla fonte corrente. Sei record senza URL utile e una posizione incoerente sono esclusi.
- Bizkaia: 135 righe di inventario senza URL pubblico non vengono promosse a webcam consultabili.
- TII Irlanda, ASFINAG, HAK, GDDKiA, SANRAL e altre fonti con condizioni incompatibili con questa acquisizione rimangono escluse/differite, con motivazione nei registri.
- API con chiave o accordi di distribuzione, risposte di rifiuto e cataloghi rimossi non sono stati aggirati. Sono documentati, tra gli altri, i casi Florida, NCDOT, Minnesota, Ontario/Alberta e altre reti 511. I riferimenti MnDOT acquisiti dal dataset pubblico selezionato non derivano dall'aggiramento del rifiuto dell'endpoint ufficiale.

Questi numeri usano unità e insiemi differenti e non formano un totale unico di esclusioni mondiali.

## Disponibilità effettivamente osservata

I **159 eventi video precedenti** rimangono integri. Le **81 osservazioni HLS positive del 13 novembre 2026** riguardano 54 URL Caltrans e 27 norvegesi. Non sono state ridatate né estese ai nuovi riferimenti. L'evidenza comprende manifest, avanzamento e campione media; non certifica ogni decoder o l'autenticità della scena.

Questa espansione aggiunge quattro controlli snapshot del 14 novembre, ore 02:57 UTC:

| Campione | Risposta | Esito |
| --- | --- | --- |
| Vitoria `CM01` | HTTP 200, JPEG | Immagine raggiungibile |
| GeoNet `ngauruhoe` | HTTP 206, JPEG | Immagine raggiungibile |
| AviationWX `02id.0` | HTTP 206, JPEG | Immagine raggiungibile |
| TrafficWatchNI `1` | HTTP 403 | Accesso ristretto per l'URL provato |

Quattro GET, massimo due simultanei, 64 KiB per risposta, timeout di otto secondi, nessun retry, nessun frame salvato. In totale 161.550 byte e 13,32 secondi. I risultati sono accettati da `snapshot_access.py`, separati dalla salute video.

Con i campioni precedenti, il DB contiene **18 verifiche immagini: 13 raggiungibili, tre accessi ristretti, un 404 e un timeout inconcludente**. Una firma JPEG/PNG non dimostra freschezza o diretta; i risultati non vengono estesi alle altre camere del provider. I timestamp delle immagini provengono dal catalogo acquisito, non da una nuova verifica dell'immagine a ogni apertura.

Tutti i 28.716 nuovi record mantengono `health.status=unverified`. Nessun booleano upstream attivo/online viene usato come prova di liveness. Il formato `snapshot` resta distinto da HLS, MJPEG e timelapse.

## Confronto con il database di sorveglianza

Il DB originale con **585.541 nodi** viene aperto in sola lettura e rimane invariato:

`SHA256 04efcf12bf90fb113038a36765d77ef7cb273923eea93c0283a080436fcb34d2`

Il matching entro 100 metri produce **24.291 coppie candidate**, riferite a **12.264 record webcam**; 3.632 hanno più di un candidato. Nessuna identità viene confermata o fusa automaticamente. Coordinate approssimative, luoghi associati e CRS non compatibili non partecipano al confronto preciso.

## Verifiche tecniche

- 72 test Python superati, inclusi diritti, portata degli host, duplicati, riferimenti secondari, GeoNet, conservazione delle prove e regole di matching.
- 16 test Node superati: 11 webcam e cinque bridge/app nativa.
- SQLite `integrity_check=ok`, zero errori di chiavi esterne.
- 33.991 record e 38.666 URL precedenti preservati; zero cambiamenti ai loro oggetti `health` e `media_access`.
- 62.707 record accettati da `prepareWebcams`, zero scarti, zero richieste ai gestori; circa 1,2 secondi di preparazione nel runtime di verifica.
- Nessun riferimento esterno con media attivo; zero promozioni upstream a live.
- Metadati originali Maryland conservati byte per byte: SHA256 `29455cc864c29eb5933420906dafc58876c77f4c7535b2008d009927e882a34e`.
- Nessun test di decodifica su browser/Android/rete Tor eseguito. Le prove DOM e URL non sostituiscono tale verifica.

File generati: SQLite non compresso 299.868.160 byte; gzip 29.167.955 byte; proiezione JSON del viewer 37.653.961 byte. Il caricamento del catalogo resta una richiesta alla sorgente dati del globo, non a ogni gestore. Non è stato introdotto un proxy aperto né un polling automatico delle camere.

## Filtro privacy

`scripts/build_webcams.py` (`private_url_reason`) e `js/webcams.mjs` (`privateUrlReason`) applicano le stesse regole a ogni URL ammesso (pagine, riferimenti, snapshot, HLS, provenienza); `tests/webcam_privacy_vectors.json` contiene i casi che entrambi devono rispettare.

- **Credenziali:** chiavi di query o frammento `user`, `usr`, `username`, `user_name`, `login`, `pass`, `pwd`, `password`, `passwd`, `passwort`, `loginuse`, `loginpas`, `auth`, `token`, `key`, `apikey`, `api_key`, `access_token`, `auth_token`, senza distinzione di maiuscole. Unica eccezione documentata (`PUBLIC_QUERY_KEY_ALLOWLIST`): `apikey` su `api.qldtraffic.qld.gov.au`, la chiave pubblica anonima stampata nella specifica QLDTraffic v1.10 (§2.1.1.1), usata solo come provenienza.
- **DNS dinamico domestico:** host sotto i servizi di router, NAS e videoregistratori (FRITZ!Box, No-IP, Dyn, DuckDNS, Dynu, Synology, QNAP, ASUS, TP-Link, Panasonic, dy.fi e altri; elenco in `DYNAMIC_DNS_SUFFIXES`), più `dyndns.*`, `no-ip.*`, `noip.*`, `freeddns.*`, `ddns.*` con qualsiasi dominio di primo livello.
- **Percorsi di dispositivo**, solo per i record OpenStreetMap e Wikidata (fonti comunitarie): axis-cgi, cgi-bin, nph-zms, GetData.cgi, /record/current.jpg, mjpg/, snapshot.cgi, video.cgi, image.jpg alla radice o con query, viewer Axis/Panasonic, ISAPI e simili, anche quando l'indirizzo del dispositivo (o l'IP della camera) è contenuto nella query di una pagina.

Un link primario privato rimuove il record; un riferimento privato viene tolto dal record. Un controllo finale rimuove ogni record che contenga ancora, in qualsiasi campo, un URL o un nome host esclusi. `reports/webcams/privacy_filter.json` elenca record, campo e regola, mai l'URL.

| Regola | Record rimossi |
| --- | ---: |
| Credenziali nella query | 149 (9 segnalati dalla revisione; 139 link al visualizzatore partner ASFINAG con `user=`, che richiede approvazione del gestore; 1 link Wikidata con `api_key`) |
| DNS dinamico domestico | 12 |
| Percorso di dispositivo | 19 |
| **Totale** | **180** (171 OSM, 9 Wikidata; nessuna fonte ufficiale) |

Il database SQLite completo (`db/qp1ng-webcams.sqlite.gz`) è un file generato e non è tracciato nel repository: vedi «Pubblicazione del database».

## Catalogo del globo: webcam visibili prima

Il livello WEBCAMS carica per primo `data/webcams-live.json`: solo i record con un HLS o uno snapshot ammessi (2.453 HLS e 13.011 snapshot, 15.464 record), in colonne con tabelle dei valori ripetuti (schema 3, `payload_kind: viewer_live`). `expandLiveCatalog` in `js/webcams.mjs` ricostruisce le stesse righe di `data/webcams.json`, quindi le schede non cambiano; i test lo verificano su tutti i 15.464 record. Il catalogo completo, con tutti i link web, si carica dal sito solo a richiesta: scheda WEB LINKS, pulsante «ALL CATALOGUE LINKS» o link a una scheda che non è tra le webcam visibili. I link HTTP non cifrati sono indicati come tali nelle schede.

| File | Record | Byte | gzip -9 | Lettura + preparazione (Node, mediana) |
| --- | ---: | ---: | ---: | ---: |
| Pacchetto, `data/webcams.json` (viewer consegnato) | 62.707 | 37.653.961 | 2.703.595 | ~0,87 s |
| `data/webcams.json` filtrato (viewer con filtro privacy) | 62.527 | 37.550.695 | 2.694.117 | ~1,0–1,2 s |
| `data/webcams-live.json` (caricato per primo) | 15.464 | 3.675.103 | 600.336 | ~0,24 s |

## Pubblicazione del database

`db/qp1ng-webcams.sqlite.gz` (circa 29 MB) non fa parte del sito né del mirror IPFS: è in `.gitignore`, GitHub Pages pubblica solo i file tracciati e `.github/workflows/ipfs.yml` lo esclude comunque. Si pubblica come allegato della release GitHub con tag fisso `webcams-db`, così il link della guida resta stabile:

`https://github.com/zonkeynet/Q-Radio-Geo/releases/download/webcams-db/qp1ng-webcams.sqlite.gz`

1. Ricostruire offline (comando sotto) e verificare i test.
2. Prima volta: GitHub → Releases → *Draft a new release* → tag `webcams-db` (nuovo, sul commit pubblicato) → allegare `db/qp1ng-webcams.sqlite.gz` → *Publish release*. Con la CLI: `gh release create webcams-db db/qp1ng-webcams.sqlite.gz --title "Webcam catalogue database" --notes "..."`.
3. Aggiornamenti: sostituire l'allegato (`gh release upload webcams-db db/qp1ng-webcams.sqlite.gz --clobber`, oppure eliminare e ricaricare l'allegato dalla pagina della release).

Nella guida (scheda Sources) il link indica che scarica da github.com e riporta le licenze: record e collegamenti OpenStreetMap ODbL 1.0, metadati Illinois DOT CC BY-SA 2.0, Wikidata CC0, le altre fonti secondo la tabella `sources`; nessuna licenza copre immagini e video collegati.

## Riproduzione offline

Il pacchetto contiene tutti i cataloghi normalizzati approvati, le ricevute, i rapporti, le prove, le policy e i dodici input Caltrans. Il database OSM originale deve provenire dal progetto e avere l'impronta sopra indicata. I cataloghi completi esclusi e i media non sono richiesti per ricostruire il DB.

Dal repository con la patch applicata, impostare `QGLOBE_INPUTS` alla cartella `inputs` del pacchetto e `QGLOBE_OSM_DB` al database originale decompresso:

```bash
python3 scripts/build_webcams.py \
  --source-dir "$QGLOBE_INPUTS/caltrans" \
  --extra-catalog "$QGLOBE_INPUTS/vegvesen.json" \
  --extra-catalog "$QGLOBE_INPUTS/emea.json" \
  --extra-catalog "$QGLOBE_INPUTS/global.json" \
  --extra-catalog "$QGLOBE_INPUTS/americas.json" \
  --extra-catalog "$QGLOBE_INPUTS/apac.json" \
  --extra-catalog "$QGLOBE_INPUTS/round4/usa.json" \
  --extra-catalog "$QGLOBE_INPUTS/round4/apac_global.json" \
  --extra-catalog "$QGLOBE_INPUTS/round4/europe.json" \
  --extra-catalog "$QGLOBE_INPUTS/round4/references.json" \
  --osm-db "$QGLOBE_OSM_DB" \
  --health "$QGLOBE_INPUTS/prior_video_checks.json" \
  --snapshot-checks "$QGLOBE_INPUTS/snapshot_sample_checks.json" \
  --snapshot-checks "$QGLOBE_INPUTS/round4/snapshot_sample_checks.json" \
  --url-repairs "$QGLOBE_INPUTS/url_repairs.json" \
  --compact-web --out data/webcams.json --live-out data/webcams-live.json \
  --db db/qp1ng-webcams.sqlite --audit-dir reports/webcams \
  --generated-at 2026-11-14T02:57:42+00:00 \
  --baseline-commit 368aed28bc4f9e4aeb80b56af9256937774c7d5c

python3 -m unittest discover -s tests -p 'test_webcams*.py'
node --test scripts/test_webcams.mjs scripts/test_native_app.mjs
```

`published_urls` deduplica gli indirizzi; `webcam_url_links` conserva i loro scopi e le associazioni. `webcam_streams` contiene solo HLS ammessi dal player. `snapshot_access_checks` conserva le verifiche immagini; `osm_candidate_links` solo candidati geografici. Per l'integrazione usare i campi dei diritti e gli stati datati, senza trasformare ogni URL in `is_live=true`.
