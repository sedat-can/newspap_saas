from scraper import parse_article
a = parse_article('https://www.ozgurpolitika.com/haberi-barisin-doktoru-gottstein-hayatini-kaybetti-207899')
print('Paragraf sayısı:', len(a['paragraphs']))
for p in a['paragraphs'][:3]:
    print('---')
    print(p[:100])