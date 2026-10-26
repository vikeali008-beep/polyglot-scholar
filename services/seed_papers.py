from .db import (
    add_or_update_vocab,
    count_owner_vocab,
    create_paper,
    get_conn,
    list_papers,
)


STARTER_VOCAB_ITEMS = [
    {
        "word": "рассматриваются",
        "lemma": "рассматриваться",
        "lang": "ru",
        "stressed_or_ipa": "рассма́триваться",
        "pos_summary": "动词 · 未完成体 (НСВ) · 复数 · 3人称",
        "meaning_zh": "被探讨，被考察，本文讨论（科技俄语核心被动词）",
        "bridge_meaning": "be considered, be examined, be discussed",
        "grammar_note": "带 -ся 未完成体被动用法，主语常为复数名词如 архитектуры / методы。",
        "context_sentence": "В рамках данного исследования рассматриваются современные архитектуры глубоких нейронных сетей.",
        "context_zh": "在本研究框架内，本文探讨了现代深度神经网络架构。",
        "paper_id": 1,
        "paper_title": "Методы глубокого обучения...",
    },
    {
        "word": "позволяющим",
        "lemma": "позволять",
        "lang": "ru",
        "stressed_or_ipa": "позволя́ть",
        "pos_summary": "长尾形动词 · 未完成体 · 主动 · 复数 · 第三格(Д.п.)",
        "meaning_zh": "使得能够……的，允许……的",
        "bridge_meaning": "allowing, enabling, permitting",
        "grammar_note": "主动现在时形动词 позволяющий 的复数第三格，与先行词 механизмам (Д.п.) 保持性数格一致。",
        "context_sentence": "Особое внимание уделяется механизмам самовнимания, позволяющим моделировать дальние контекстные зависимости.",
        "context_zh": "文中特别关注能够对长距离上下文依赖进行建模的自注意力机制。",
        "paper_id": 1,
        "paper_title": "Методы глубокого обучения...",
    },
    {
        "word": "склонения",
        "lemma": "склонение",
        "lang": "ru",
        "stressed_or_ipa": "склоне́ние",
        "pos_summary": "名词 · 中性 · 单数 · 第二格·属格 (Р.п.)",
        "meaning_zh": "变格；（物理）偏角",
        "bridge_meaning": "declension, inflection",
        "grammar_note": "система склонения существительных = 名词变格体系（连续属格链）。",
        "context_sentence": "Развитая система склонения существительных и спряжения глаголов приводит к значительному росту размера словаря.",
        "context_zh": "发达的名词变格体系与动词变位体系导致词表规模大幅增长。",
        "paper_id": 1,
        "paper_title": "Методы глубокого обучения...",
    },
    {
        "word": "свидетельствуют",
        "lemma": "свидетельствовать",
        "lang": "ru",
        "stressed_or_ipa": "свиде́тельствовать",
        "pos_summary": "动词 · 未完成体 (НСВ) · 复数 · 3人称",
        "meaning_zh": "表明，证明，证实（常接 о + 第六格 / о том, что）",
        "bridge_meaning": "indicate, demonstrate, bear witness to",
        "grammar_note": "经典论文结论句型：эксперименты свидетельствуют о том, что...（实验表明……）。",
        "context_sentence": "Проведённые эксперименты убедительно свидетельствуют о том, что учёт грамматических признаков повышает точность перевода.",
        "context_zh": "所开展的实验有力地表明，引入语法特征可提升翻译准确率。",
        "paper_id": 1,
        "paper_title": "Методы глубокого обучения...",
    },
    {
        "word": "dispensing",
        "lemma": "dispense",
        "lang": "en",
        "stressed_or_ipa": "/dɪˈspens/",
        "pos_summary": "verb · AWL 学术搭配 (dispense with)",
        "meaning_zh": "省去，摒弃，无需（常与 with 连用）",
        "bridge_meaning": "обходи́ться без · исключа́ть",
        "grammar_note": "dispensing with recurrence = 彻底省去循环结构（现在分词短语作伴随状语）。",
        "context_sentence": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        "context_zh": "我们提出了一种全新的简洁网络架构 Transformer，它完全基于注意力机制，彻底摒弃了循环与卷积。",
        "paper_id": 2,
        "paper_title": "Self-Attention Mechanisms...",
    },
    {
        "word": "precludes",
        "lemma": "preclude",
        "lang": "en",
        "stressed_or_ipa": "/prɪˈkluːd/",
        "pos_summary": "verb · 正式学术动词",
        "meaning_zh": "阻碍，排除，使……成为不可能",
        "bridge_meaning": "исключа́ть · препя́тствовать",
        "grammar_note": "preclude sth. (from doing) = 妨碍/使无法实现某事，学术论文中替代 prevent 的高阶动词。",
        "context_sentence": "This inherently sequential nature precludes parallelization within training examples.",
        "context_zh": "这种固有的顺序计算特性阻碍了训练样本内部的并行化。",
        "paper_id": 2,
        "paper_title": "Self-Attention Mechanisms...",
    },
    {
        "word": "heterogeneous",
        "lemma": "heterogeneous",
        "lang": "en",
        "stressed_or_ipa": "/ˌhetərəˈdʒiːniəs/",
        "pos_summary": "adjective · AWL 学术核心词汇",
        "meaning_zh": "异质的，多样的，由不同成分组成的",
        "bridge_meaning": "гетероге́нный · неодноро́дный",
        "grammar_note": "构词：hetero-（异）+ gen（种类）+ -eous；反义词为 homogeneous（同质的）。",
        "context_sentence": "Furthermore, the learned representations generalize effectively to heterogeneous linguistic tasks.",
        "context_zh": "此外，模型习得的表征能够有效泛化至异质的多样化语言学任务。",
        "paper_id": 2,
        "paper_title": "Self-Attention Mechanisms...",
    },
]


def ensure_owner_starter_vocab(owner_id: str) -> None:
    if not owner_id:
        return
    conn = get_conn()
    flag = conn.execute(
        "SELECT value FROM user_settings WHERE owner_id = ? AND key = '_starter_vocab_init'",
        (owner_id,),
    ).fetchone()
    conn.close()
    if flag:
        return

    if count_owner_vocab(owner_id) == 0:
        for item in reversed(STARTER_VOCAB_ITEMS):
            add_or_update_vocab(item, owner_id=owner_id)

    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (owner_id, key, value) VALUES (?, '_starter_vocab_init', 'true')",
        (owner_id,),
    )
    conn.commit()
    conn.close()


def ensure_seed_data() -> None:
    existing = list_papers("sample")
    if any(p["is_sample"] for p in existing):
        return

    # 1. Russian Paper 1: Deep Learning & NLP / Machine Translation (AI & CS)
    ru_paper_1 = [
        {
            "id": "p1",
            "type": "heading",
            "text": "Аннотация",
            "zh_text": "摘要",
            "stressed_text": "Аннота́ция",
        },
        {
            "id": "p2",
            "type": "paragraph",
            "text": (
                "В рамках данного исследования рассматриваются современные архитектуры глубоких нейронных сетей, "
                "применяемые в задачах автоматической обработки естественного языка и нейронного машинного перевода. "
                "Особое внимание уделяется механизмам самовнимания, позволяющим моделировать дальние контекстные "
                "зависимости между лексическими единицами без использования рекуррентных вычислений."
            ),
            "zh_text": (
                "在本研究框架内，本文探讨了应用于自然语言自动处理与神经机器翻译任务中的现代深度神经网络架构。"
                "文中特别关注自注意力机制，该机制能够在不使用循环计算的情况下，对词汇单元之间的长距离上下文依赖关系进行建模。"
            ),
            "stressed_text": (
                "В ра́мках да́нного иссле́дования рассма́триваются совреме́нные архитекту́ры глубо́ких нейро́нных сете́й, "
                "применя́емые в зада́чах автомати́ческой обрабо́тки есте́ственного языка́ и нейро́нного маши́нного перево́да. "
                "Осо́бое внима́ние уделя́ется механи́змам самовнима́ния, позволя́ющим модели́ровать да́льние конте́кстные "
                "зави́симости ме́жду лекси́ческими едини́цами без испо́льзования рекурре́нтных вычисле́ний."
            ),
        },
        {
            "id": "p3",
            "type": "heading",
            "text": "1. Введение и постановка задачи",
            "zh_text": "1. 引言与问题提出",
            "stressed_text": "1. Введе́ние и постано́вка зада́чи",
        },
        {
            "id": "p4",
            "type": "paragraph",
            "text": (
                "Морфологическое богатство синтетических языков, к числу которых относится русский язык, "
                "создаёт существенные трудности при построении статистических и нейросетевых языковых моделей. "
                "Развитая система склонения существительных и спряжения глаголов приводит к значительному росту "
                "размера словаря и появлению большого числа редких словоформ."
            ),
            "zh_text": (
                "综合语（俄语即属于此类语言）丰富的词法形态，在构建统计语言模型与神经网络语言模型时造成了显著困难。"
                "发达的名词变格体系与动词变位体系导致词表规模大幅膨胀，并产生大量低频罕见词形。"
            ),
            "stressed_text": (
                "Морфологи́ческое бога́тство синтети́ческих языко́в, к числу́ кото́рых отно́сится ру́сский язы́к, "
                "создаёт суще́ственные тру́дности при построе́нии статисти́ческих и нейросетевы́х языковы́х моде́лей. "
                "Ра́звитая систе́ма склоне́ния существи́тельных и спряже́ния глаго́лов приво́дит к значи́тельному ро́сту "
                "разме́ра словаря́ и появле́нию большо́го числа́ ре́дких словофо́рм."
            ),
        },
        {
            "id": "p5",
            "type": "heading",
            "text": "2. Методология и экспериментальные результаты",
            "zh_text": "2. 研究方法论与实验结果",
            "stressed_text": "2. Методоло́гия и эксперимента́льные результа́ты",
        },
        {
            "id": "p6",
            "type": "paragraph",
            "text": (
                "Предложенный авторами гибридный алгоритм сегментации учитывает морфемную структуру слова, "
                "сохраняя корневые морфемы и отделяя флективные окончания. "
                "Таким образом, проведённые эксперименты убедительно свидетельствуют о том, что учёт "
                "грамматических признаков повышает точность перевода научных текстов на 14,6% по сравнению с базовыми подходами."
            ),
            "zh_text": (
                "作者提出的混合切分算法充分考虑了单词的词素结构，在保留词根词素的同时剥离屈折词尾。"
                "因此，所开展的实验有力地表明：与基线方法相比，引入语法特征可使科技文献的翻译准确率提升 14.6%。"
            ),
            "stressed_text": (
                "Предло́женный а́вторами гибри́дный алгори́тм сегмента́ции учи́тывает морфе́мную структу́ру сло́ва, "
                "сохраня́я корневы́е морфе́мы и отделя́я флекти́вные оконча́ния. "
                "Таки́м о́бразом, проведённые экспериме́нты убеди́тельно свиде́тельствуют о том, что учёт "
                "граммати́ческих при́знаков повыша́ет то́чность перево́да нау́чных те́кстов на 14,6% по сравне́нию с ба́зовыми подхо́дами."
            ),
        },
    ]

    p1_id = create_paper(
        title="Методы глубокого обучения в задачах обработки естественного языка и машинного перевода",
        title_zh="自然语言处理与机器翻译任务中的深度学习方法",
        authors="А. В. Соколов, Е. Н. Морозова (МГУ / РАН)",
        source="Вестник компьютерных и информационных технологий · 精选示例",
        lang="ru",
        paragraphs=ru_paper_1,
        notes="💡 精读提示：\n1. 点击第1段中的「рассматриваются」「применяемые」「позволяющим」，观察科技俄语最核心的 -ся 被动句与形动词后置定语。\n2. 开启顶部「标注重音 (Ударение)」即可对比俄语重音位置。",
        is_sample=True,
    )

    # 2. English Paper 1: Sequence Transduction & Self-Attention (AI / ML)
    en_paper_1 = [
        {
            "id": "p1",
            "type": "heading",
            "text": "Abstract",
            "zh_text": "摘要",
            "stressed_text": "",
        },
        {
            "id": "p2",
            "type": "paragraph",
            "text": (
                "Dominant sequence transduction models are based on complex recurrent or convolutional neural networks "
                "that include an encoder and a decoder. The best performing models also connect the encoder and decoder "
                "through an attention mechanism. We propose a new simple network architecture, the Transformer, "
                "based solely on attention mechanisms, dispensing with recurrence and convolutions entirely."
            ),
            "zh_text": (
                "主流的序列转导模型均基于包含编码器与解码器的复杂循环神经网络或卷积神经网络。"
                "性能最优的模型还会通过注意力机制连接编码器与解码器。我们提出了一种全新的简洁网络架构——Transformer，"
                "它完全基于注意力机制构建，彻底摒弃了循环结构与卷积操作。"
            ),
            "stressed_text": "",
        },
        {
            "id": "p3",
            "type": "heading",
            "text": "1. Architectural Motivation and Parallelization",
            "zh_text": "1. 架构动机与并行化机制",
            "stressed_text": "",
        },
        {
            "id": "p4",
            "type": "paragraph",
            "text": (
                "Recurrent models typically factor computation along the symbol positions of the input and output sequences, "
                "generating a sequence of hidden states as a function of the previous hidden state. "
                "This inherently sequential nature precludes parallelization within training examples, which becomes critical "
                "at longer sequence lengths, as memory constraints limit batching across examples."
            ),
            "zh_text": (
                "循环模型通常沿着输入与输出序列的符号位置分解计算，将前一个隐藏状态作为函数输入来依次生成隐藏状态序列。"
                "这种固有的顺序计算特性阻碍了训练样本内部的并行化，而在序列长度较长时这一瓶颈尤为关键，因为显存限制制约了跨样本的批处理规模。"
            ),
            "stressed_text": "",
        },
        {
            "id": "p5",
            "type": "heading",
            "text": "2. Empirical Evaluation",
            "zh_text": "2. 实证评估",
            "stressed_text": "",
        },
        {
            "id": "p6",
            "type": "paragraph",
            "text": (
                "Experiments on two machine translation tasks demonstrate these models to be superior in quality "
                "while being significantly more parallelizable and requiring substantially less time to train. "
                "Furthermore, the learned representations generalize effectively to heterogeneous linguistic tasks "
                "with limited labeled data."
            ),
            "zh_text": (
                "在两项机器翻译任务上的实验表明，此类模型不仅在翻译质量上表现更优，而且并行化程度显著提高，所需训练时间大幅缩短。"
                "此外，模型习得的表征在标注数据有限的情况下，依然能够有效泛化至异质的多样化语言学任务。"
            ),
            "stressed_text": "",
        },
    ]

    p2_id = create_paper(
        title="Self-Attention Mechanisms and Parallelizable Sequence Transduction Architectures",
        title_zh="自注意力机制与可并行化序列转导架构研究",
        authors="Vaswani et al. (Adapted Academic Reader Edition)",
        source="Advances in Neural Information Processing · 精选示例",
        lang="en",
        paragraphs=en_paper_1,
        notes="💡 精读提示：\n1. 点击「transduction」「dispensing」「precludes」「heterogeneous」查看中文释义、英文原版释义以及对应的俄语学术同义词（实现英俄双向串学）。\n2. 点击句末「拆解」按钮体验分词状语与定语从句结构分析。",
        is_sample=True,
    )

    # 3. Russian Paper 2: Quantum & Semiconductor Physics (STEM Russian)
    ru_paper_2 = [
        {
            "id": "p1",
            "type": "heading",
            "text": "Аннотация",
            "zh_text": "摘要",
            "stressed_text": "Аннота́ция",
        },
        {
            "id": "p2",
            "type": "paragraph",
            "text": (
                "В настоящей работе исследуются квантово-размерные эффекты в низкоразмерных полупроводниковых "
                "гетероструктурах при низких температурах. Показано, что пространственное ограничение носителей заряда "
                "существенно изменяет энергетический спектр электронов и оптические свойства исследуемых образцов."
            ),
            "zh_text": (
                "本文研究了低温条件下低维半导体异质结中的量子尺寸效应。研究表明，载流子的空间受限效应会显著改变电子的能谱以及所研究样品的光学性质。"
            ),
            "stressed_text": (
                "В настоя́щей рабо́те иссле́дуются ква́нтово-разме́рные эффе́кты в низкоразме́рных полупроводнико́вых "
                "гетерострукту́рах при ни́зких температу́рах. Пока́зано, что простра́нственное ограниче́ние носи́телей заря́да "
                "суще́ственно изменя́ет энергети́ческий спектр электро́нов и опти́ческие сво́йства иссле́дуемых образцо́в."
            ),
        },
    ]

    create_paper(
        title="Исследование квантово-размерных эффектов в низкоразмерных полупроводниковых гетероструктурах",
        title_zh="低维半导体异质结中的量子尺寸效应研究",
        authors="Д. И. Жоресов, Н. А. Белов (ФТИ им. А.Ф. Иоффе)",
        source="Физика и техника полупроводников · 精选示例",
        lang="ru",
        paragraphs=ru_paper_2,
        is_sample=True,
    )

    # 4. English Paper 2: Cognitive Science & Multilingual Acquisition
    en_paper_2 = [
        {
            "id": "p1",
            "type": "heading",
            "text": "Abstract",
            "zh_text": "摘要",
            "stressed_text": "",
        },
        {
            "id": "p2",
            "type": "paragraph",
            "text": (
                "Cross-linguistic transfer plays a pivotal role in third-language academic reading comprehension, "
                "particularly when learners simultaneously acquire typologically distinct languages such as English and Russian. "
                "Empirical evidence suggests that explicit morphological awareness facilitates lexical inference and syntactic parsing "
                "in dense scientific discourse."
            ),
            "zh_text": (
                "跨语言迁移在第三语言学术阅读理解中起着关键作用，尤其是当学习者同时习得英语与俄语这类类型学特征迥异的语言时。"
                "实证证据表明，显性的词法形态意识有助于在高信息密度的科学语篇中进行词义推断与句法解析。"
            ),
            "stressed_text": "",
        },
    ]

    create_paper(
        title="Cross-Linguistic Transfer and Morphological Awareness in Bilingual Academic Reading",
        title_zh="双语学术阅读中的跨语言迁移与词法形态意识",
        authors="M. K. Lindholm, S. V. Karpova",
        source="Journal of Applied Psycholinguistics · 精选示例",
        lang="en",
        paragraphs=en_paper_2,
        is_sample=True,
    )

    ensure_owner_starter_vocab("default")
