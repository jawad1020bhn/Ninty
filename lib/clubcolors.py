# -*- coding: utf-8 -*-
"""Ugradjene boje klubova (primarna za gradijent, sekundarna). Radi bez interneta.
Korisnik moze dodati/ispraviti klub u data/boje.json: {"Ime Kluba": "#rrggbb"} ili ["#prim","#sek"]."""
RAW = """
Manchester United FC|#da291c|#fbe122
Arsenal FC|#ef0107|#063672
Chelsea FC|#034694|#dba111
Liverpool FC|#c8102e|#00b2a9
Leeds United FC|#1d428a|#ffcd00
Everton FC|#003399|#ffffff
Fulham FC|#cc0000|#000000
Manchester City FC|#6cabdd|#1c2c5b
Newcastle United FC|#241f20|#41b6e6
Tottenham Hotspur FC|#132257|#ffffff
West Ham United FC|#7a263a|#1bb1e7
Aston Villa FC|#670e36|#95bfe5
AFC Bournemouth|#da291c|#000000
Brighton & Hove Albion FC|#0057b8|#ffcd00
Burnley FC|#6c1d45|#99d6ea
Sunderland AFC|#eb172b|#ffffff
Wolverhampton Wanderers FC|#fdb913|#231f20
Crystal Palace FC|#1b458f|#c4122e
Brentford FC|#e30613|#fbb800
Nottingham Forest FC|#dd0000|#ffffff
Leicester City FC|#003090|#fdbe11
Southampton FC|#d71920|#130c0e
Ipswich Town FC|#3a64a3|#ffffff
Watford FC|#fbee23|#ed2127
Middlesbrough FC|#e8112d|#ffffff
Birmingham City FC|#0000ff|#ffffff
Blackburn Rovers FC|#009fe3|#ffffff
Bristol City FC|#e21a23|#ffffff
Charlton Athletic FC|#d4021d|#ffffff
Coventry City FC|#59cbe8|#ffffff
Derby County FC|#ffffff|#000000
Hull City AFC|#f5a12d|#000000
Millwall FC|#001d5c|#ffffff
Oxford United FC|#f1c40f|#002147
Portsmouth FC|#001489|#ffffff
Preston North End FC|#ffffff|#001489
Queens Park Rangers FC|#1d5ba4|#ffffff
Sheffield Wednesday FC|#0e00f7|#ffffff
Stoke City FC|#e03a3e|#ffffff
Swansea City AFC|#ffffff|#000000
Falkirk FC|#00205b|#ffffff
Celtic FC|#00843d|#ffffff
Rangers FC|#1b458f|#ffffff
Aberdeen FC|#e2231a|#ffffff
Dundee FC|#0b3f8c|#ffffff
Dundee United FC|#f77f00|#000000
Heart of Midlothian FC|#8a1538|#ffffff
Hibernian FC|#00a651|#ffffff
Kilmarnock FC|#1b458f|#ffffff
Livingston FC|#fcd116|#000000
Motherwell FC|#f5b800|#8a1538
St. Mirren FC|#000000|#ffffff
Real Madrid CF|#ffffff|#febe10
FC Barcelona|#a50044|#004d98
Atlético de Madrid|#cb3524|#272e61
Sevilla FC|#d4001a|#ffffff
Valencia CF|#ee7600|#000000
Villarreal CF|#ffe667|#005187
Athletic Club|#ee2523|#000000
Real Sociedad de Fútbol|#0067b1|#ffffff
Real Betis Balompié|#0bb363|#ffffff
Girona FC|#cd2534|#ffffff
CA Osasuna|#d91a21|#0a346f
RCD Mallorca|#e20613|#000000
Rayo Vallecano|#ffffff|#e53027
RCD Espanyol|#007fc8|#ffffff
Celta de Vigo|#8ac3ee|#ffffff
Getafe CF|#005999|#ffffff
Deportivo Alavés|#005ca9|#ffffff
UD Las Palmas|#ffe400|#1b3a8c
Elche CF|#ffffff|#00964a
Real Oviedo|#1f3a93|#ffffff
Levante UD|#a40d22|#143c8a
CD Leganés|#2f9d4e|#ffffff
Real Valladolid CF|#5e2a84|#ffffff
Cádiz CF|#fdd800|#003d99
UD Almería|#e30613|#ffffff
Córdoba CF|#00873e|#ffffff
Real Zaragoza|#003d99|#ffffff
Racing de Santander|#00a651|#ffffff
RC Deportivo de La Coruña|#0a5bb8|#ffffff
Real Sporting de Gijón|#e30613|#ffffff
SD Eibar|#a3182d|#2a4aa0
CD Mirandés|#e30613|#000000
AD Ceuta FC|#ffffff|#000000
Cultural y Deportiva Leonesa|#ffffff|#e30613
Real Sociedad de Fútbol B|#0067b1|#ffffff
FC Bayern München|#dc052d|#0066b2
Borussia Dortmund|#fde100|#000000
RB Leipzig|#dd0741|#001f47
Bayer 04 Leverkusen|#e32221|#000000
Eintracht Frankfurt|#e1000f|#000000
VfB Stuttgart|#e32219|#ffffff
SV Werder Bremen|#1d9053|#ffffff
Borussia Mönchengladbach|#00a050|#000000
VfL Wolfsburg|#65b32e|#ffffff
SC Freiburg|#e2001a|#000000
Sport-Club Freiburg|#e2001a|#000000
1. FC Union Berlin|#eb1923|#fed403
TSG Hoffenheim|#1961b5|#ffffff
FC Augsburg|#ba3733|#046530
1. FSV Mainz 05|#c3141e|#ffffff
FC St. Pauli|#6d3f2a|#ffffff
Hamburger SV|#0069b4|#ffffff
1. FC Köln|#e2001a|#ffffff
FC Schalke 04|#004d9d|#ffffff
Hertha BSC|#004e9e|#ffffff
Hannover 96|#00a650|#000000
Fortuna Düsseldorf|#e2001a|#ffffff
SV Darmstadt 98|#004e9e|#ffffff
SC Paderborn 07|#004e9e|#000000
SC Preußen Münster|#00a650|#000000
DSC Arminia Bielefeld|#005ca9|#000000
Holstein Kiel|#005ca9|#ffffff
SV Elversberg|#000000|#ffffff
1. FC Heidenheim 1846|#e2001a|#003d99
Hansa Rostock|#005ca9|#e2001a
FC Hansa Rostock|#005ca9|#e2001a
SG Dynamo Dresden|#fdd600|#000000
SSV Jahn Regensburg|#e2001a|#ffffff
TSV 1860 München|#00a0e1|#ffffff
VfL Bochum 1848|#005ca9|#ffffff
Juventus FC|#000000|#ffffff
FC Internazionale Milano|#0068a8|#000000
AC Milan|#fb090b|#000000
SSC Napoli|#12a0d7|#ffffff
SS Lazio|#87d8f7|#ffffff
AS Roma|#8e1f2f|#f0bc42
Atalanta BC|#1e71b8|#000000
ACF Fiorentina|#482e92|#ffffff
Torino FC|#8a1e1e|#ffffff
Bologna FC 1909|#1a2f5a|#a21c26
Udinese Calcio|#000000|#ffffff
Genoa CFC|#0a2a5c|#c8102e
Cagliari Calcio|#9b1b30|#0a2a5c
Hellas Verona FC|#1a3c8f|#fdd800
US Lecce|#f1c40f|#e30613
Parma Calcio 1913|#fdd800|#003d99
Como 1907|#00539f|#ffffff
US Sassuolo|#00a650|#000000
US Cremonese|#b5b5b5|#e30613
AC Pisa 1909|#000000|#0a2a5c
Venezia FC|#e87722|#0a6b3c
UC Sampdoria|#0c4da2|#ffffff
Palermo FC|#f4a6c1|#000000
SSC Bari|#e30613|#ffffff
Spezia Calcio|#ffffff|#000000
Modena FC|#fdd800|#003d99
Cesena FC|#000000|#ffffff
Empoli FC|#0066b3|#ffffff
Frosinone Calcio|#fdd800|#003d99
US Catanzaro 1929|#e30613|#fdd800
Carrarese Calcio 1908|#fdd800|#003d99
SS Juve Stabia|#fdd800|#003d99
Pescara Calcio 1936|#7ec8e3|#ffffff
Virtus Entella|#00a0e1|#ffffff
Paris Saint-Germain FC|#004170|#da291c
Olympique Marseille|#2faee0|#ffffff
Olympique Lyonnais|#0b3d91|#da291c
AS Monaco FC|#e30613|#ffffff
Lille OSC|#e01e13|#1e2a5a
OGC Nice Côte d'Azur|#e30613|#000000
RC Lens|#fdd800|#e30613
Stade Rennais FC|#e30613|#000000
Stade Brestois 29|#e30613|#ffffff
FC Nantes|#fdd800|#00a650
Toulouse FC|#5a2d82|#ffffff
RC Strasbourg Alsace|#0099d8|#ffffff
AJ Auxerre|#0a5bb8|#ffffff
Angers SCO|#000000|#ffffff
FC Lorient|#f58220|#000000
FC Metz|#800020|#ffffff
Paris FC|#003d99|#ffffff
Havre AC|#5aa5d8|#0a2a5c
SL Benfica|#e30613|#ffffff
Lisboa e Benfica|#e30613|#ffffff
FC Porto|#003893|#ffffff
Sporting CP|#008057|#ffffff
SC Braga|#e30613|#ffffff
Vitória SC|#ffffff|#000000
Moreirense FC|#00844a|#ffffff
Gil Vicente FC|#e30613|#003d99
Rio Ave FC|#00a650|#ffffff
FC Arouca|#fdd800|#003d99
GD Estoril Praia|#fdd800|#003d99
Casa Pia AC|#ffffff|#000000
CF Estrela da Amadora|#e30613|#00a650
FC Alverca|#e30613|#003d99
CD Santa Clara|#e30613|#ffffff
CD Tondela|#00a650|#fdd800
AVS Futebol SAD|#e30613|#ffffff
AFC Ajax|#d2122e|#ffffff
PSV Eindhoven|#ee1c25|#ffffff
Feyenoord Rotterdam|#e30613|#ffffff
AZ Alkmaar|#e30613|#ffffff
FC Twente|#e30613|#ffffff
FC Utrecht|#e30613|#ffffff
SC Heerenveen|#0067b1|#ffffff
NEC Nijmegen|#e30613|#00a650
Go Ahead Eagles|#e30613|#fdd800
Sparta Rotterdam|#e30613|#ffffff
FC Groningen|#00a650|#ffffff
Fortuna Sittard|#fdd800|#00a650
PEC Zwolle|#0067b1|#ffffff
NAC Breda|#fdd800|#000000
Heracles Almelo|#000000|#ffffff
SC Telstar|#ffffff|#000000
Excelsior Rotterdam|#e30613|#000000
FC Volendam|#f58220|#000000
Club Brugge KV|#0a5bb8|#000000
RSC Anderlecht|#5b2c83|#ffffff
Royal Antwerp FC|#e30613|#ffffff
KAA Gent|#003d99|#ffffff
KRC Genk|#0067b1|#ffffff
Royale Union Saint-Gilloise|#fdd800|#003d99
Sporting Charleroi SC|#000000|#ffffff
Royal Standard de Liège|#e30613|#ffffff
KV Mechelen|#fdd800|#e30613
OH Leuven|#00a650|#ffffff
KVC Westerlo|#fdd800|#003d99
SV Zulte Waregem|#e30613|#00a650
FCV Dender EH|#e30613|#ffffff
RAAL La Louvière|#00a650|#e30613
Galatasaray AŞ|#a90432|#fdb912
Fenerbahçe SK|#fdd800|#00205b
Beşiktaş JK|#000000|#ffffff
Trabzonspor Kulübü|#7a1f3d|#00a0e1
Medipol Başakşehir FK|#f58220|#1b2a4a
Fraport-TAV Antalyaspor|#e30613|#ffffff
Gaziantep FK|#e30613|#000000
Gençlerbirliği SK|#e30613|#000000
Göztepe SK|#fdd800|#e30613
Kasimpaşa SK|#1b2a6b|#ffffff
Kocaelispor|#00a650|#000000
Samsunspor|#e30613|#ffffff
Yukatel Kayserispor|#fdd800|#e30613
Çaykur Rizespor|#00a650|#0067b1
İttifak Holding Konyaspor|#00a650|#ffffff
GNK Dinamo Zagreb|#0a3d91|#ffffff
HNK Hajduk Split|#0a3d91|#ffffff
HNK Rijeka|#ffffff|#0a3d91
FK Crvena Zvezda|#e30613|#ffffff
FK Partizan|#000000|#ffffff
FC Red Bull Salzburg|#e30613|#001f47
SK Rapid Wien|#00a650|#ffffff
SK Sturm Graz|#000000|#ffffff
LASK Linz|#e30613|#000000
Wolfsberger AC|#000000|#ffffff
FC Basel 1893|#e30613|#003d99
BSC Young Boys|#fdd800|#000000
FC Lugano|#000000|#ffffff
FC Lausanne-Sport|#0067b1|#ffffff
FC København|#ffffff|#0a3d91
FC Midtjylland|#000000|#e30613
Brøndby IF|#fdd800|#0067b1
FC Nordsjælland|#e30613|#000000
AGF Aarhus|#ffffff|#0a3d91
Odense Boldklub|#ffffff|#0a3d91
Randers FC|#0067b1|#ffffff
Silkeborg IF|#e30613|#ffffff
Viborg FF|#00a650|#ffffff
Vejle BK|#e30613|#ffffff
SønderjyskE|#0067b1|#ffffff
FC Fredericia|#e30613|#ffffff
Malmö FF|#5ac8fa|#ffffff
Djurgårdens IF|#0a3d91|#fdd800
BK Häcken|#fdd800|#000000
Rosenborg BK|#ffffff|#000000
FK Bodø/Glimt|#fdd800|#000000
Molde FK|#0067b1|#ffffff
HJK Helsinki|#0a3d91|#ffffff
Legia Warszawa|#00a650|#000000
KKS Lech Poznań|#0a3d91|#ffffff
RKS Raków Częstochowa|#e30613|#0a3d91
Jagiellonia Białystok|#fdd800|#e30613
SK Slavia Praha|#e30613|#ffffff
AC Sparta Praha|#a50034|#fdd800
FC Viktoria Plzeň|#e30613|#0a3d91
SK Slovan Bratislava|#5ac8fa|#ffffff
ŠK Slovan Bratislava|#5ac8fa|#ffffff
Ferencvárosi TC|#00a650|#ffffff
CFR 1907 Cluj|#8a1538|#ffffff
PFC CSKA Sofia|#e30613|#ffffff
Olympiacos FC|#e30613|#ffffff
Panathinaikos FC|#00a650|#ffffff
AEK Athens FC|#fdd800|#000000
PAOK FC|#000000|#ffffff
Aris FC|#fdd800|#000000
Omonoia FC|#00a650|#ffffff
APOEL FC|#fdd800|#003d99
Pafos FC|#0067b1|#ffffff
Atromitos FC|#003d99|#ffffff
Asteras Tripolis FC|#fdd800|#000000
Levadiakos FC|#000000|#ffffff
OFI Crete FC|#ffffff|#000000
Panetolikos FC|#00a650|#ffffff
Panserraikos FC|#e30613|#000000
Volos FC|#0067b1|#ffffff
AE Kifisia FC|#00a650|#ffffff
Athens FC|#ffffff|#e30613
Maccabi Haifa FC|#00a650|#ffffff
Hapoel Be'er Sheva FC|#e30613|#ffffff
Qarabağ FK|#000000|#ffffff
FC Sheriff Tiraspol|#fdd800|#000000
FC Astana|#fdd800|#0067b1
FC Kairat|#fdd800|#000000
FC Dynamo Kiev|#0067b1|#ffffff
FC Shakhtar Donetsk|#f58220|#000000
FK Spartak Moskva|#e30613|#ffffff
FK Krasnodar|#00a650|#000000
FK Lokomotiv Moskva|#00a650|#e30613
FK Dinamo Moskva|#0067b1|#ffffff
FK Rubin Kazan|#a50034|#ffffff
FK Rostov|#fdd800|#0067b1
FK Akhmat Grozny|#00a650|#ffffff
PFC Sochi|#0067b1|#ffffff
FK Orenburg|#0067b1|#e30613
PFK Krylia Sovetov Samara|#5ac8fa|#ffffff
FK Pari Nizhny Novgorod|#00a650|#ffffff
FK Dinamo Makhachkala|#5ac8fa|#ffffff
FK Akron Togliatti|#e30613|#ffffff
FC Baltika Kaliningrad|#fdd800|#0067b1
Al Ahly SC|#e30613|#ffffff
Wydad AC|#e30613|#ffffff
Espérance Sportive de Tunis|#fdd800|#e30613
Al Hilal SFC|#0067b1|#ffffff
Al Nassr FC|#fdd800|#003d99
Al Ittihad Club|#fdd800|#000000
Al Ahli Saudi FC|#00a650|#ffffff
Al Qadsiah FC|#fdd800|#003d99
Al Shabab FC|#ffffff|#00a650
Ettifaq Club|#00a650|#ffffff
Al Fateh SC|#00a650|#ffffff
Al Fayha Club|#e30613|#fdd800
Al Khaleej FC|#fdd800|#003d99
Al Kholood Club|#e30613|#ffffff
Al Okhdood Club|#fdd800|#e30613
Al Riyadh SC|#00a650|#ffffff
Al Taawoun FC|#e30613|#ffffff
Damac FC|#00a650|#ffffff
NEOM SC|#fdd800|#0067b1
Shanghai Port FC|#e30613|#ffffff
Beijing Guoan FC|#00a650|#ffffff
Buriram United FC|#0067b1|#e30613
True Bangkok United FC|#e30613|#ffffff
Pohang Steelers|#e30613|#000000
FC Tokyo|#0a3d91|#e30613
Kashima Antlers|#a50034|#ffffff
Kashiwa Reysol|#fdd800|#000000
Kawasaki Frontale|#5ac8fa|#000000
Yokohama F. Marinos|#0067b1|#e30613
Yokohama FC|#5ac8fa|#ffffff
Urawa Red Diamonds|#e30613|#000000
Gamba Osaka|#0067b1|#000000
Nagoya Grampus|#e30613|#fdd800
Sanfrecce Hiroshima|#5b2c83|#ffffff
Shimizu S-Pulse|#f58220|#000000
Shonan Bellmare|#7ec850|#ffffff
Kyoto Sanga FC|#5b2c83|#ffffff
Tokyo Verdy|#00a650|#ffffff
FC Machida Zelvia|#0a3d91|#fdd800
Fagiano Okayama|#a50034|#ffffff
Albirex Niigata|#f58220|#0067b1
Avispa Fukuoka|#8a1538|#ffffff
Los Angeles Galaxy|#00245d|#ffffff
Inter Miami CF|#f7b5cd|#231f20
Atlanta United FC|#80000a|#000000
Austin FC|#00b140|#000000
Charlotte FC|#1a85c8|#000000
Chicago Fire FC|#9a1b2c|#ffffff
FC Cincinnati|#f05323|#003087
Colorado Rapids|#862633|#8bb8e8
Columbus Crew|#fedd00|#000000
D.C. United|#000000|#e30613
Houston Dynamo FC|#f4911e|#101820
Minnesota United FC|#8cd2f4|#231f20
CF Montréal|#000000|#0067b1
Nashville SC|#ece83a|#1f1646
New England Revolution|#0a2240|#c63323
New York City FC|#6cace4|#041e42
New York Red Bulls|#ed1e36|#ffc20e
Orlando City SC|#633492|#fdd100
Philadelphia Union|#071b2c|#b19b69
Portland Timbers|#004812|#ecd630
San Diego FC|#a4a9ad|#0a1f44
San Jose Earthquakes|#0067b1|#000000
Seattle Sounders FC|#5d9741|#005595
Sporting Kansas City|#93b1d7|#002f65
St. Louis CITY SC|#d02f2f|#0a1f44
Toronto FC|#b81137|#455560
Vancouver Whitecaps FC|#00245e|#9dc2ea
CF Monterrey|#002b5c|#ffffff
Tigres UANL|#fdb913|#00529f
CF América|#fdd800|#003d99
CF Pachuca|#003d99|#ffffff
Club León|#00a650|#ffffff
CA Boca Juniors|#003d99|#fdd800
CA River Plate|#ffffff|#e30613
Racing Club|#7ec8e3|#ffffff
CA San Lorenzo de Almagro|#003d99|#e30613
CA Banfield|#00a650|#ffffff
CA Tigre|#003d99|#e30613
CA Belgrano|#7ec8e3|#ffffff
CA Tucumán|#7ec8e3|#ffffff
CA Central Córdoba|#000000|#ffffff
CA Aldosivi|#fdd800|#00a650
CA Barracas Central|#e30613|#ffffff
CA Newell's Old Boys|#e30613|#000000
Deportivo Riestra|#ffffff|#000000
Club Estudiantes de La Plata|#e30613|#ffffff
AA Argentinos Juniors|#e30613|#ffffff
Instituto Atlético Central Córdoba|#e30613|#ffffff
CD Godoy Cruz Antonio Tomba|#003d99|#ffffff
SE Palmeiras|#006437|#ffffff
SC Corinthians Paulista|#000000|#ffffff
São Paulo FC|#e30613|#000000
Santos FC|#ffffff|#000000
CR Vasco da Gama|#000000|#ffffff
Fluminense FC|#8a1538|#00a650
Botafogo FR|#000000|#ffffff
Botafogo FC|#000000|#ffffff
Clube Atlético Mineiro|#000000|#ffffff
Clube Athletico Paranaense|#e30613|#000000
SC Internacional|#e30613|#ffffff
Grêmio FBPA|#0a8fd4|#000000
Fortaleza EC|#003d99|#e30613
Ceará SC|#000000|#ffffff
EC Vitória|#e30613|#000000
EC Juventude|#00a650|#ffffff
Red Bull Bragantino|#ffffff|#e30613
Mirassol FC|#fdd800|#00a650
Sport Club do Recife|#e30613|#000000
Coritiba FC|#00a650|#ffffff
Cuiabá EC|#00a650|#fdd800
Goiás EC|#00a650|#ffffff
Avaí FC|#003d99|#ffffff
Criciúma EC|#fdd800|#000000
Operário Ferroviário EC|#000000|#ffffff
Grêmio Novorizontino|#fdd800|#000000
Volta Redonda FC|#fdd800|#003d99
Amazonas FC|#00a650|#fdd800
Paysandu SC|#7ec8e3|#003d99
Associação Ferroviária de Esportes|#8a1538|#ffffff
Clube de Regatas Brasil|#003d99|#ffffff
CSD Colo-Colo|#000000|#ffffff
CD Universidad Católica|#003d99|#ffffff
CD Huachipato|#000000|#ffffff
CD Cobresal|#f58220|#ffffff
CD Ñublense|#e30613|#000000
CD O'Higgins|#5ac8fa|#ffffff
CD La Serena|#8a1538|#ffffff
CD Unión La Calera|#e30613|#ffffff
Audax Italiano La Florida|#00a650|#ffffff
Club Deportes Iquique|#5ac8fa|#ffffff
Club Deportes Limache|#fdd800|#000000
Everton de Viña del Mar|#fdd800|#003d99
CD Nacional|#ffffff|#e30613
Club Nacional de Football|#ffffff|#003d99
Liverpool FC Montevideo|#003d99|#000000
Universitario de Deportes|#fdd800|#8a1538
Club Sporting Cristal|#5ac8fa|#ffffff
Alianza FC|#003d99|#ffffff
LDU Quito|#ffffff|#e30613
Club Cerro Porteño|#003d99|#e30613
Club Bolívar|#7ec8e3|#ffffff
Club Always Ready|#ffffff|#e30613
Caracas FC|#e30613|#ffffff
Deportivo Táchira FC|#fdd800|#000000
América de Cali|#e30613|#ffffff
CDP Junior FC|#e30613|#ffffff
CD Once Caldas|#ffffff|#00a650
CD Deportes Tolima|#8a1538|#fdd800
Club Deportes Tolima|#8a1538|#fdd800
CD La Equidad Seguros|#00a650|#fdd800
CA Bucaramanga|#fdd800|#00a650
Unión Magdalena|#003d99|#ffffff
Boyacá Chicó FC|#fdd800|#003d99
Llaneros FC|#e30613|#fdd800
Asociación Deportivo Pasto|#fdd800|#e30613
Albania|#e30613|#000000
Algeria|#00a650|#ffffff
Andorra|#003d99|#fdd800
Angola|#e30613|#000000
Armenia|#e30613|#003d99
Azerbaijan|#5ac8fa|#00a650
Belarus|#e30613|#00a650
Bolivia|#00a650|#e30613
Bosnia and Herzegovina|#003d99|#fdd800
Burkina Faso|#00a650|#e30613
Canada|#e30613|#ffffff
Cape Verde|#003d99|#ffffff
Curaçao|#003d99|#fdd800
Cyprus|#ffffff|#003d99
DR Congo|#5ac8fa|#e30613
Côte d'Ivoire|#f58220|#00a650
Estonia|#003d99|#ffffff
Faroe Islands|#003d99|#e30613
Gabon|#fdd800|#00a650
Georgia|#e30613|#ffffff
Ghana|#fdd800|#e30613
Gibraltar|#e30613|#ffffff
Guinea|#e30613|#fdd800
Iceland|#003d99|#e30613
India|#003d99|#f58220
Indonesia|#e30613|#ffffff
Iraq|#00a650|#ffffff
Israel|#003d99|#ffffff
Jordan|#e30613|#ffffff
Korea DPR|#e30613|#003d99
Kosovo|#003d99|#fdd800
Kuwait|#003d99|#ffffff
Lebanon|#e30613|#00a650
Liechtenstein|#003d99|#e30613
Lithuania|#fdd800|#00a650
Luxembourg|#e30613|#5ac8fa
Mali|#00a650|#fdd800
Malta|#e30613|#ffffff
Moldova|#003d99|#fdd800
Montenegro|#e30613|#fdd800
North Macedonia|#e30613|#fdd800
Oman|#e30613|#ffffff
Panama|#e30613|#003d99
Qatar|#8a1538|#ffffff
Serbia|#e30613|#003d99
Suriname|#00a650|#e30613
Thailand|#003d99|#e30613
United Arab Emirates|#e30613|#ffffff
Uzbekistan|#003d99|#ffffff
Venezuela|#8a1538|#fdd800
Zambia|#00a650|#f58220
FC Istiklol Dushanbe|#003d99|#ffffff
FC Nasaf|#0067b1|#ffffff
FC Südtirol|#ffffff|#e30613
World Selection|#003d99|#fdd800
"""
import json as _json, os as _os, re as _re
def _norm(n):
    n = (n or '').lower()
    n = _re.sub(r'\b(fc|cf|sc|ac|afc|fk|sk|cd|ca|club|de|the|1\.|sv|ssc|us|rc|rcd|ud)\b', ' ', n)
    return _re.sub(r'[^a-z0-9]+', '', n)
BUILTIN = {}
for _l in RAW.strip().splitlines():
    _p = _l.split('|')
    if len(_p) == 3:
        BUILTIN[_p[0]] = [_p[1], _p[2]]
def merged(data_dir):
    d = dict(BUILTIN)
    try:
        with open(_os.path.join(data_dir, 'boje.json'), encoding='utf-8') as f:
            for k, v in (_json.load(f) or {}).items():
                d[k] = [v, v] if isinstance(v, str) else list(v)[:2]
    except Exception:
        pass
    return d
