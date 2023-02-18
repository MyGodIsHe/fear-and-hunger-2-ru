# fear-and-hunger-2-ru
Переводчик игры Страх и Голод 2: Термина

# Использование

Скачать перевод из гуглдока в кэш:
```bash
./update_from_doc.py > translate_cache.json 
```

Перевести игру:
```bash
./translate.py --game-dir game-2-root --line-limit 60
```

Распечатать перевод из кэша для загрузки в гуглдок:
```bash
./print_translate_cache.py > doc.txt
```